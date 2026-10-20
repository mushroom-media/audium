"""Runs Alembic migrations at startup, with a backup of the SQLite file before any upgrade."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool

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


def migrate(db_url: str, backups_dir: Path | None = None) -> None:
    cfg = alembic_config(db_url)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    current = current_revision(db_url)
    if current == head:
        return
    if current is not None and backups_dir is not None and db_url.startswith("sqlite:///"):
        _backup_sqlite(Path(db_url.removeprefix("sqlite:///")), backups_dir, current)
    log.info("db.migrate", from_revision=current, to_revision=head)
    command.upgrade(cfg, "head")


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
