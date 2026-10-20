"""Database access: one Engine, explicit read and write transactions.

SQLite specifics:
- WAL lets readers (API) run while a writer (scanner) commits.
- Write transactions use BEGIN IMMEDIATE. A deferred transaction that reads first and writes
  later can fail with SQLITE_BUSY without waiting for busy_timeout when another process
  committed in between; taking the write lock up front avoids that.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, create_engine, event
from sqlalchemy.engine import Engine

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=15000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA cache_size=-32000",
    "PRAGMA mmap_size=268435456",
)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        kwargs: dict = {}
        if self.is_sqlite:
            kwargs.update(connect_args={"check_same_thread": False}, pool_size=10, max_overflow=30)
        self.engine: Engine = create_engine(url, **kwargs)
        if self.is_sqlite:
            self._install_sqlite_hooks()

    def _install_sqlite_hooks(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _on_connect(dbapi_conn, _record):
            # Let SQLAlchemy (not pysqlite) control transactions, see "begin" below.
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            for pragma in _SQLITE_PRAGMAS:
                cur.execute(pragma)
            cur.close()

        @event.listens_for(self.engine, "begin")
        def _on_begin(conn: Connection):
            conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.info.get("immediate") else "BEGIN")

    @contextmanager
    def read(self) -> Iterator[Connection]:
        """Consistent snapshot for reads. Keep it short: open readers delay WAL checkpoints."""
        with self.engine.connect() as conn:
            yield conn

    @contextmanager
    def write(self) -> Iterator[Connection]:
        """Write transaction, committed on success and rolled back on error."""
        with self.engine.connect() as conn:
            conn.info["immediate"] = True
            try:
                with conn.begin():
                    yield conn
            finally:
                conn.info.pop("immediate", None)

    def dispose(self) -> None:
        self.engine.dispose()
