"""Per-user preferences, stored server-side so they follow the user across devices."""

import json

from sqlalchemy import Connection, select

from audium.db.dialect import insert_for
from audium.db.schema import user_settings
from audium.errors import BadRequest
from audium.util import now_ms

# key -> allowed values; the first one is the default
OPTIONS: dict[str, tuple[str, ...]] = {
    # "server" follows the server language (server setting language).
    "language": ("server", "de", "en"),
    "theme": ("system", "dark", "light"),
    # auto: original file when the browser can play it, otherwise transcode at high quality.
    # high/medium/low: always transcode (saves bandwidth on slow connections).
    "stream_quality": ("auto", "high", "medium", "low"),
    # Keyboard shortcuts in the web UI.
    "shortcuts": ("on", "off"),
    # Plain ←/→ seek 10 seconds (off: they are left to the page; Shift+←/→ skip tracks either way).
    "seek_keys": ("off", "on"),
    # Volume levelling with ReplayGain tags: off, per track, or per album (keeps an album's dynamics).
    "replay_gain": ("off", "track", "album"),
    # Crossfade between tracks that follow each other on their own (length: crossfade_s).
    "crossfade": ("off", "on"),
    # Library: the tab it opens with ("last": the one open last time on that device), the sorting,
    # and whether the artist tab lists album artists only.
    "library_tab": ("last", "tracks", "albums", "artists"),
    "track_sort": ("title", "added", "year"),
    "album_sort": ("title", "artist", "year", "added"),
    "artist_role": ("album", "all"),
    # Artists without their own picture: the newest album cover, or a placeholder. "server" follows
    # the admin's choice (server setting artist_album_covers).
    "artist_images": ("server", "on", "off"),
}

# key -> (min, max, default) for whole-number settings
RANGES: dict[str, tuple[int, int, int]] = {
    "crossfade_s": (1, 12, 5),
    # How lively the blurred cover behind "now playing" moves: 0 stands still, 25 the slow base pace, 50 twice that.
    "backdrop_motion": (0, 100, 50),
}


def _valid(key: str, value) -> bool:
    if key in RANGES:
        lo, hi, _ = RANGES[key]
        return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi
    return value in OPTIONS[key]


def get_settings(conn: Connection, user_id: int) -> dict:
    raw = conn.execute(select(user_settings.c.settings_json).where(user_settings.c.user_id == user_id)).scalar()
    stored = json.loads(raw) if raw else {}
    out = {k: stored.get(k) if stored.get(k) in allowed else allowed[0] for k, allowed in OPTIONS.items()}
    out |= {k: stored[k] if _valid(k, stored.get(k)) else default for k, (_, _, default) in RANGES.items()}
    return out


def update_settings(conn: Connection, user_id: int, changes: dict) -> dict:
    for key, value in changes.items():
        if key not in OPTIONS and key not in RANGES:
            raise BadRequest(f"unknown setting {key!r}")
        if not _valid(key, value):
            if key in RANGES:
                raise BadRequest(f"{key} must be a whole number from {RANGES[key][0]} to {RANGES[key][1]}")
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
