"""Per-user preferences, stored server-side so they follow the user across devices."""

import json

from sqlalchemy import Connection, select

from audium.db.dialect import insert_for
from audium.db.schema import user_settings
from audium.errors import BadRequest
from audium.util import now_ms

# key -> allowed values; the first one is the default
OPTIONS: dict[str, tuple[str, ...]] = {
    "theme": ("system", "dark", "light"),
    # auto: original file when the browser can play it, otherwise transcode at high quality.
    # high/medium/low: always transcode (saves bandwidth on slow connections).
    "stream_quality": ("auto", "high", "medium", "low"),
}


def get_settings(conn: Connection, user_id: int) -> dict:
    raw = conn.execute(select(user_settings.c.settings_json).where(user_settings.c.user_id == user_id)).scalar()
    stored = json.loads(raw) if raw else {}
    return {k: stored.get(k) if stored.get(k) in allowed else allowed[0] for k, allowed in OPTIONS.items()}


def update_settings(conn: Connection, user_id: int, changes: dict) -> dict:
    for key, value in changes.items():
        if key not in OPTIONS:
            raise BadRequest(f"unknown setting {key!r}")
        if value not in OPTIONS[key]:
            raise BadRequest(f"{key} must be one of {', '.join(OPTIONS[key])}")
    merged = {**get_settings(conn, user_id), **changes}
    ts = now_ms()
    stmt = insert_for(conn, user_settings).values(user_id=user_id, settings_json=json.dumps(merged), updated_at=ts)
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[user_settings.c.user_id], set_={"settings_json": json.dumps(merged), "updated_at": ts}
        )
    )
    return merged
