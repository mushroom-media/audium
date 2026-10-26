"""Fixed-window failure counter for login-like endpoints, stored in the DB so it survives restarts."""

from sqlalchemy import Connection, select

from audium.db.dialect import insert_for
from audium.db.schema import login_attempts


def retry_after(conn: Connection, key: str, now: int, window_ms: int, limit: int) -> int:
    """Seconds until `key` may try again, 0 if it is not blocked."""
    row = conn.execute(
        select(login_attempts.c.window_start, login_attempts.c.count).where(login_attempts.c.key == key)
    ).first()
    if row is None or row.window_start + window_ms <= now or row.count < limit:
        return 0
    return max(1, (row.window_start + window_ms - now + 999) // 1000)


def failures(conn: Connection, key: str, now: int, window_ms: int) -> int:
    """Failures of `key` in the current window."""
    row = conn.execute(
        select(login_attempts.c.window_start, login_attempts.c.count).where(login_attempts.c.key == key)
    ).first()
    if row is None or row.window_start + window_ms <= now:
        return 0
    return row.count


def register_failure(conn: Connection, key: str, now: int, window_ms: int) -> None:
    row = conn.execute(
        select(login_attempts.c.window_start, login_attempts.c.count).where(login_attempts.c.key == key)
    ).first()
    if row is None or row.window_start + window_ms <= now:
        stmt = insert_for(conn, login_attempts).values(key=key, window_start=now, count=1)
        conn.execute(
            stmt.on_conflict_do_update(index_elements=[login_attempts.c.key], set_={"window_start": now, "count": 1})
        )
    else:
        conn.execute(
            login_attempts.update().where(login_attempts.c.key == key).values(count=login_attempts.c.count + 1)
        )


def reset(conn: Connection, key: str) -> None:
    conn.execute(login_attempts.delete().where(login_attempts.c.key == key))


def prune(conn: Connection, now: int, window_ms: int) -> None:
    conn.execute(login_attempts.delete().where(login_attempts.c.window_start + window_ms < now))
