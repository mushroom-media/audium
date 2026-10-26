"""The play queue a user left off with, to continue on another device (Subsonic savePlayQueue /
getPlayQueue). One per user; the last save wins."""

import json

from sqlalchemy import Connection, delete, select

from audium.db.dialect import insert_for
from audium.db.schema import play_queue
from audium.errors import BadRequest
from audium.util import now_ms

MAX_ITEMS = 5000


def save(
    conn: Connection,
    user_id: int,
    track_ids: list[int],
    current: int | None,
    position_ms: int,
    changed_by: str | None,
) -> None:
    if not track_ids:
        conn.execute(delete(play_queue).where(play_queue.c.user_id == user_id))
        return
    if len(track_ids) > MAX_ITEMS:
        raise BadRequest(f"a play queue holds at most {MAX_ITEMS} tracks")
    if current is not None and current not in track_ids:
        current = None
    values = {
        "track_ids_json": json.dumps(track_ids),
        "current_track_id": current,
        "position_ms": max(0, position_ms),
        "changed_by": (changed_by or "")[:64] or None,
        "updated_at": now_ms(),
    }
    stmt = insert_for(conn, play_queue).values(user_id=user_id, **values)
    conn.execute(stmt.on_conflict_do_update(index_elements=[play_queue.c.user_id], set_=values))


def load(conn: Connection, user_id: int) -> dict | None:
    row = conn.execute(select(play_queue).where(play_queue.c.user_id == user_id)).first()
    if row is None:
        return None
    return {
        "track_ids": json.loads(row.track_ids_json),
        "current": row.current_track_id,
        "position_ms": row.position_ms,
        "changed_by": row.changed_by,
        "updated_at": row.updated_at,
    }
