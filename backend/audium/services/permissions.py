"""Who may do what with a playlist. Every playlist endpoint goes through `require_playlist`.

| action                         | owner | editor | viewer | visibility=users | others (incl. admin) |
|--------------------------------|-------|--------|--------|------------------|----------------------|
| view, play                     |   ✓   |   ✓    |   ✓    |        ✓         |   – (404)            |
| add / remove / reorder tracks  |   ✓   |   ✓    |   –    |        –         |   – (404)            |
| rename, describe, visibility   |   ✓   |   –    |   –    |        –         |   – (404)            |
| share, delete                  |   ✓   |   –    |   –    |        –         |   – (404)            |

Without view access the answer is 404, so nobody can probe which private playlists exist.
Admins get no extra rights here: they manage accounts, not other people's playlists.
"""

from typing import Literal

from sqlalchemy import Connection, select

from audium.db.schema import playlist_shares, playlists
from audium.errors import Forbidden, NotFound
from audium.services.users import User

Role = Literal["owner", "editor", "viewer"]
Need = Literal["view", "edit", "manage"]

_ALLOWED: dict[Need, set[str]] = {
    "view": {"owner", "editor", "viewer"},
    "edit": {"owner", "editor"},
    "manage": {"owner"},
}


def playlist_role(conn: Connection, user: User, playlist) -> Role | None:
    if playlist.owner_id == user.id:
        return "owner"
    share = conn.execute(
        select(playlist_shares.c.role).where(
            playlist_shares.c.playlist_id == playlist.id, playlist_shares.c.user_id == user.id
        )
    ).scalar()
    if share in ("editor", "viewer"):
        return share
    if playlist.visibility == "users":
        return "viewer"
    return None


def require_playlist(conn: Connection, user: User, playlist_id: int, need: Need):
    """(playlist row, role) if `user` may `need`; NotFound without view access, else Forbidden."""
    row = conn.execute(select(playlists).where(playlists.c.id == playlist_id)).first()
    role = playlist_role(conn, user, row) if row is not None else None
    if role is None:
        raise NotFound("playlist not found")
    if role not in _ALLOWED[need]:
        raise Forbidden("only the owner can do this" if need == "manage" else "you can only view this playlist")
    return row, role
