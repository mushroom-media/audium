"""Command line entry point: `audium <command>` (also `python -m audium`)."""

import argparse
import os
import secrets
import sys
import urllib.request

from audium.config import Settings


def _settings() -> Settings:
    return Settings()


def _setup(proc: str) -> Settings:
    from audium.logging import configure_logging

    settings = _settings()
    configure_logging(settings.log_level, settings.log_format, proc)
    return settings


def _check_data_dir(settings: Settings) -> None:
    from audium.logging import get_logger

    log = get_logger("audium.cli")
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.data_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        log.error(
            "startup.data_dir_not_writable",
            path=str(settings.data_dir),
            uid=os.getuid() if hasattr(os, "getuid") else None,
            error=str(exc),
            hint="The /data volume must be writable by the container user (default uid 1000). "
            "Fix with: chown -R 1000:1000 <host data folder>, or set `user:` in docker-compose.",
        )
        sys.exit(1)


def cmd_serve(_args) -> int:
    """Migrate, then run API and workers under the supervisor (the container's main command)."""
    settings = _setup("supervisor")
    _check_data_dir(settings)
    from audium.db.engine import Database
    from audium.db.migrate import migrate
    from audium.jobs.queue import reset_running
    from audium.supervisor import Supervisor, default_children

    migrate(settings.db_url, settings.backups_dir)
    db = Database(settings.db_url)
    with db.write() as conn:
        reset_running(conn)
    db.dispose()
    return Supervisor(default_children()).run()


def cmd_api(_args) -> int:
    import uvicorn

    from audium.main import create_app

    settings = _setup("api")
    config = uvicorn.Config(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxies,
        log_config=None,
        access_log=settings.access_log,
        timeout_graceful_shutdown=5,
        server_header=False,
    )
    uvicorn.Server(config).run()
    return 0


def cmd_worker(args) -> int:
    settings = _setup(f"worker-{args.queue}")
    from audium.db.engine import Database
    from audium.jobs.worker import Worker

    db = Database(settings.db_url)
    if args.queue == "scan":
        from audium.scanner.tasks import ScanScheduler, make_handlers

        worker = Worker(db, "scan", make_handlers(db, settings), on_idle=ScanScheduler(db, settings))
    elif args.queue == "analysis":
        from audium.analysis.tasks import AnalysisScheduler
        from audium.analysis.tasks import make_handlers as analysis_handlers

        # Background work must never compete with playback or the UI.
        if hasattr(os, "nice"):
            os.nice(19)
        worker = Worker(db, "analysis", analysis_handlers(db, settings), on_idle=AnalysisScheduler(db, settings))
    else:
        print(f"unknown queue {args.queue!r}", file=sys.stderr)
        return 2
    worker.install_signal_handlers()
    worker.run_forever()
    db.dispose()
    return 0


def cmd_migrate(_args) -> int:
    settings = _setup("cli")
    from audium.db.migrate import migrate

    migrate(settings.db_url, settings.backups_dir)
    return 0


def cmd_healthcheck(_args) -> int:
    settings = _settings()
    url = f"http://127.0.0.1:{settings.port}{settings.base_path}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:  # noqa: S310 - fixed local URL
            return 0 if resp.status == 200 else 1
    except Exception:
        return 1


def cmd_admin(args) -> int:
    settings = _setup("cli")
    from audium.db.engine import Database
    from audium.services import users as user_service

    db = Database(settings.db_url)
    password = args.password or secrets.token_urlsafe(12)
    with db.write() as conn:
        if args.action == "create-user":
            user_service.create_user(conn, args.username, password, role=args.role)
        else:  # reset-password: for a locked-out admin
            row = user_service.find_by_username(conn, args.username)
            if row is None:
                print(f"no user {args.username!r}", file=sys.stderr)
                return 1
            admin = user_service.User(row.id, row.username, row.display_name, "admin", "active", 0, None)
            user_service.update_user(conn, admin, row.id, password=password, status="active")
    if not args.password:
        print(f"password for {args.username}: {password}")
    return 0


def cmd_gen_testlib(args) -> int:
    settings = _setup("cli")
    from audium.devtools.gen_testlib import generate_db, generate_files

    if args.mode == "files":
        generate_files(args.out, args.tracks, seed=args.seed)
    else:
        generate_db(settings, args.tracks, seed=args.seed)
    return 0


def cmd_loadtest(args) -> int:
    from audium.devtools.loadtest import run

    return run(args.url, args.user, args.password, args.requests, args.concurrency, args.search_p95_ms)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="audium", description="Self-hosted music streaming server")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="run migrations, API and workers (default container command)").set_defaults(
        func=cmd_serve
    )
    sub.add_parser("api", help="run only the HTTP API").set_defaults(func=cmd_api)
    p = sub.add_parser("worker", help="run one background worker")
    p.add_argument("--queue", default="scan", choices=["scan", "analysis"])
    p.set_defaults(func=cmd_worker)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    sub.add_parser("healthcheck", help="exit 0 if the local API is healthy").set_defaults(func=cmd_healthcheck)

    p = sub.add_parser("admin", help="account recovery")
    p.add_argument("action", choices=["create-user", "reset-password"])
    p.add_argument("username")
    p.add_argument("--password", help="default: generate and print one")
    p.add_argument("--role", default="admin", choices=["admin", "user"])
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("gen-testlib", help="generate a synthetic library for performance tests")
    p.add_argument(
        "--mode",
        choices=["files", "db"],
        default="files",
        help="files: real tagged audio files; db: rows directly in the database",
    )
    p.add_argument("--tracks", type=int, default=100_000)
    p.add_argument("--out", default="/music/testlib", help="target folder (files mode)")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_gen_testlib)

    p = sub.add_parser("loadtest", help="measure API latency against a running instance")
    p.add_argument("--url", default="http://127.0.0.1:8080")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--requests", type=int, default=2000)
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--search-p95-ms", type=float, default=200.0, help="fail if search p95 is above this")
    p.set_defaults(func=cmd_loadtest)

    args = parser.parse_args(argv)
    sys.exit(args.func(args))
