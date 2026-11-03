"""How the requesting user wants things shown, for the current request only.

Set by `api.deps.viewer` (web API) and the Subsonic dispatcher once the user is known; read deep
in the services (e.g. `library.artist_select`) instead of passing it through every call.
"""

from contextvars import ContextVar

from sqlalchemy import Connection

from audium.services.server_settings import server_setting
from audium.services.settings import get_settings

# Artists without their own picture show the cover of their newest album. None: not set for this
# request, shown like "on".
artist_album_covers: ContextVar[bool | None] = ContextVar("artist_album_covers", default=None)


def wants_artist_album_covers(conn: Connection, user_id: int) -> bool:
    """The user's choice, or the server's when they left it at "server"."""
    mine = get_settings(conn, user_id)["artist_images"]
    return (server_setting(conn, "artist_album_covers") if mine == "server" else mine) == "on"


def apply(conn: Connection, user_id: int) -> None:
    artist_album_covers.set(wants_artist_album_covers(conn, user_id))
