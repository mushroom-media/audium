"""Runs Alembic migrations at startup, with a backup of the SQLite file before any upgrade."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, pool

from audium.logging import get_logger
from audium.util import now_ms

log = get_logger(__name__)
_KEEP_BACKUPS = 3


def alembic_config(db_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def current_revision(db_url: str) -> str | None:
    engine = create_engine(db_url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _transactional_engine(db_url: str) -> Engine:
    """An engine whose transactions also cover CREATE/ALTER/DROP.

    Python's sqlite3 commits on its own before DDL, so a migration stopped half-way (container
    stopped during the first start) would leave some tables behind and no revision. With the
    driver's own transaction handling off and an explicit BEGIN, SQLite rolls all of it back.
    """
    engine = create_engine(db_url, poolclass=pool.NullPool)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _no_driver_transactions(dbapi_conn, _record):
            dbapi_conn.isolation_level = None

        @event.listens_for(engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def migrate(db_url: str, backups_dir: Path | None = None) -> None:
    cfg = alembic_config(db_url)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    current = current_revision(db_url)
    if current == head:
        return
    db_path = Path(db_url.removeprefix("sqlite:///")) if db_url.startswith("sqlite:///") else None
    if current is None and db_path is not None:
        _set_aside_unfinished_first_start(db_path)
    if current is not None and backups_dir is not None and db_path is not None:
        _backup_sqlite(db_path, backups_dir, current)
    log.info("db.migrate", from_revision=current, to_revision=head)
    engine = _transactional_engine(db_url)
    try:
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
    finally:
        engine.dispose()


def _set_aside_unfinished_first_start(db_path: Path) -> None:
    """A database with tables but no revision comes from a first start that was stopped while
    0.1.0 created the schema (its migrations were not yet atomic). Without accounts it holds
    nothing of the user's: keep it next to the database under another name and start fresh.
    With accounts, refuse to guess."""
    if not db_path.exists():
        return
    con = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        users = con.execute("SELECT count(*) FROM users").fetchone()[0] if "users" in tables else 0
    finally:
        con.close()
    if not tables:
        return
    if users:
        raise RuntimeError(
            f"{db_path} has {users} account(s) but no schema version. Restore a copy from the backups "
            "folder, or move the file away to start with an empty database."
        )
    target = db_path.with_name(f"{db_path.name}.unfinished-{now_ms()}")
    for suffix in ("", "-wal", "-shm"):
        part = db_path.with_name(db_path.name + suffix)
        if part.exists():
            part.rename(target.with_name(target.name + suffix))
    log.warning("db.unfinished_first_start", moved_to=str(target))


def _backup_sqlite(db_path: Path, backups_dir: Path, revision: str) -> None:
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / f"audium-{revision}-{now_ms()}.db"
    # sqlite3 backup API produces a consistent copy even with a WAL file next to it.
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    log.info("db.backup", path=str(target))
    old = sorted(backups_dir.glob("audium-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in old[_KEEP_BACKUPS:]:
        p.unlink(missing_ok=True)
