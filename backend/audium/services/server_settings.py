"""Server-wide settings (Einstellungen > Server, admins only), stored in app_state.

Per-user preferences live in services/settings.py.
"""

from sqlalchemy import Connection

from audium.db.state import get_state, set_state
from audium.errors import BadRequest

# key -> allowed values; the first one is the default
OPTIONS: dict[str, tuple[str, ...]] = {
    # Artists without their own picture (artist.jpg) show the cover of their newest album.
    "artist_album_covers": ("on", "off"),
}

_PREFIX = "settings."


def server_setting(conn: Connection, key: str) -> str:
    value = get_state(conn, _PREFIX + key)
    return value if value in OPTIONS[key] else OPTIONS[key][0]


def get_server_settings(conn: Connection) -> dict:
    return {key: server_setting(conn, key) for key in OPTIONS}


def update_server_settings(conn: Connection, changes: dict) -> tuple[dict, set[str]]:
    """The settings after `changes`, and the keys whose value actually changed."""
    for key, value in changes.items():
        if key not in OPTIONS:
            raise BadRequest(f"unknown setting {key!r}")
        if value not in OPTIONS[key]:
            raise BadRequest(f"{key} must be one of {', '.join(OPTIONS[key])}")
    before = get_server_settings(conn)
    changed = {key for key, value in changes.items() if before[key] != value}
    for key in changed:
        set_state(conn, _PREFIX + key, changes[key])
    return {**before, **changes}, changed
