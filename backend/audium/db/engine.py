"""Database access: one Engine, explicit read and write transactions.

SQLite specifics:
- WAL lets readers (API) run while a writer (scanner) commits.
- Write transactions use BEGIN IMMEDIATE. A deferred transaction that reads first and writes
  later can fail with SQLITE_BUSY without waiting for busy_timeout when another process
  committed in between; taking the write lock up front avoids that.
- Reads can be limited to N at a time per process (`read_concurrency`). Measured with 100k
  tracks: 4 parallel reader connections in one process gave 25 requests/s, one at a time 41/s.
  Parallel SQLite connections in one process contend on SQLite's global mutexes, and the
  queries take milliseconds, so queueing them is faster than running them side by side.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, create_engine, event
from sqlalchemy.engine import Engine

_SQLITE_BUSY_TIMEOUT = "PRAGMA busy_timeout=15000"
_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    _SQLITE_BUSY_TIMEOUT,
    "PRAGMA temp_store=MEMORY",
    "PRAGMA cache_size=-32000",
    "PRAGMA mmap_size=268435456",
)


class Database:
    def __init__(self, url: str, *, read_concurrency: int | None = None) -> None:
        self.url = url
        self._read_gate = threading.BoundedSemaphore(read_concurrency) if read_concurrency else None
        self._local = threading.local()
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
    def read(self, urgent: bool = False) -> Iterator[Connection]:
        """Consistent snapshot for reads. Keep it short: open readers delay WAL checkpoints.
        Re-entrant within a thread, so a nested read never waits for its own gate. `urgent` skips
        the queue, for the few quick reads someone is waiting on (the start of a stream)."""
        depth = getattr(self._local, "depth", 0)
        gated = self._read_gate is not None and depth == 0 and not urgent
        if gated:
            self._read_gate.acquire()
        self._local.depth = depth + 1
        try:
            with self.engine.connect() as conn:
                yield conn
        finally:
            self._local.depth = depth
            if gated:
                self._read_gate.release()

    @contextmanager
    def write(self, busy_timeout_ms: int | None = None) -> Iterator[Connection]:
        """Write transaction, committed on success and rolled back on error. Not gated: a write
        waiting for the database lock must not hold up readers. `busy_timeout_ms` (SQLite):
        wait at most this long for the lock instead of the default 15 s, for writes that may
        be skipped (they fail with OperationalError "database is locked" then)."""
        with self.engine.connect() as conn:
            conn.info["immediate"] = True
            raw = conn.connection.dbapi_connection if self.is_sqlite and busy_timeout_ms is not None else None
            if raw is not None:
                raw.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            try:
                with conn.begin():
                    yield conn
            finally:
                conn.info.pop("immediate", None)
                if raw is not None:
                    raw.execute(_SQLITE_BUSY_TIMEOUT)

    def dispose(self) -> None:
        self.engine.dispose()
