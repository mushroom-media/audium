"""Server-wide settings (Einstellungen > Server, admins only), stored in app_state.

Per-user preferences live in services/settings.py.
"""

from sqlalchemy import Connection

from audium.db.state import get_state, set_state
from audium.errors import BadRequest

MAX_ANALYSIS_WORKERS = 16
_HOURS = tuple(f"{h:02d}" for h in range(24))


def _default_first(default: str, values: tuple[str, ...]) -> tuple[str, ...]:
    return (default, *(v for v in values if v != default))


# key -> allowed values; the first one is the default
OPTIONS: dict[str, tuple[str, ...]] = {
    # Artists without their own picture (artist.jpg) show the cover of their newest album. The
    # default for users who leave it at "server" (see services/view_prefs.py).
    "artist_album_covers": ("on", "off"),
    # Without an artist.jpg, a folder.jpg in the artist folder (Artist/folder.jpg next to
    # Artist/Album/) is the artist's picture. Applied by the scan (scanner/scan.py).
    "artist_folder_images": ("on", "off"),
    # Audio analysis (analysis/tasks.py): parallel processes, one CPU core each ("default":
    # AUDIUM_ANALYSIS_WORKERS), a pause switch, and an optional time window in server time (full
    # hours, from inclusive, until exclusive; it may span midnight).
    "analysis_workers": ("default", *(str(n) for n in range(1, MAX_ANALYSIS_WORKERS + 1))),
    "analysis_paused": ("off", "on"),
    "analysis_schedule": ("always", "window"),
    "analysis_from": _default_first("01", _HOURS),
    "analysis_until": _default_first("07", _HOURS),
    # Interfaces (Einstellungen > Schnittstellen). Incoming: the Subsonic API under /rest
    # (api/subsonic/routing.py) and the audium apps, which call /api with a bearer token
    # (api/deps.py). Outgoing: the analysis models from essentia.upf.edu (analysis/tasks.py).
    # The AUDIUM_* switches (subsonic_enabled, analysis_download_models) stay above these: off
    # there is off here. ListenBrainz is the radio source "artists" (analysis/sources.py).
    "subsonic_api": ("on", "off"),
    "app_access": ("on", "off"),
    "model_download": ("on", "off"),
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
