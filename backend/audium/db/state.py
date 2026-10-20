"""Small key/value store for process-wide state (setup token hash, worker heartbeats, counters)."""

from sqlalchemy import Connection, select

from audium.db.dialect import insert_for
from audium.db.schema import app_state
from audium.util import now_ms

LIBRARY_GENERATION = "library.generation"


def get_state(conn: Connection, key: str) -> str | None:
    return conn.execute(select(app_state.c.value).where(app_state.c.key == key)).scalar()


def set_state(conn: Connection, key: str, value: str) -> None:
    ts = now_ms()
    stmt = insert_for(conn, app_state).values(key=key, value=value, updated_at=ts)
    conn.execute(stmt.on_conflict_do_update(index_elements=[app_state.c.key], set_={"value": value, "updated_at": ts}))


def delete_state(conn: Connection, key: str) -> None:
    conn.execute(app_state.delete().where(app_state.c.key == key))


def bump_library_generation(conn: Connection) -> None:
    """Invalidates cached list counts in the API process."""
    current = int(get_state(conn, LIBRARY_GENERATION) or 0)
    set_state(conn, LIBRARY_GENERATION, str(current + 1))
