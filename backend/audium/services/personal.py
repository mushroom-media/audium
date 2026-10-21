"""Per-user data: favorites and listening history. Always scoped to the requesting user."""

from sqlalchemy import Connection, delete, func, select

from audium.db.dialect import insert_for
from audium.db.pagination import fetch_ordered
from audium.db.schema import albums, artists, favorites, play_history, tracks
from audium.errors import BadRequest, NotFound
from audium.services.library import album_item, album_select, artist_item, artist_select, track_item, track_select
from audium.util import now_ms

ITEM_TYPES = {"track": tracks, "album": albums, "artist": artists}
MAX_FAVORITE_IDS = 50_000
HISTORY_RETENTION = 10_000  # entries per user


def _table(item_type: str):
    if item_type not in ITEM_TYPES:
        raise BadRequest("type must be track, album or artist")
    return ITEM_TYPES[item_type]


def set_favorite(conn: Connection, user_id: int, item_type: str, item_id: int, on: bool) -> None:
    table = _table(item_type)
    if on:
        if conn.execute(select(table.c.id).where(table.c.id == item_id)).scalar() is None:
            raise NotFound(f"{item_type} not found")
        stmt = insert_for(conn, favorites).values(
            user_id=user_id, item_type=item_type, item_id=item_id, created_at=now_ms()
        )
        conn.execute(stmt.on_conflict_do_nothing())
    else:
        conn.execute(
            delete(favorites).where(
                favorites.c.user_id == user_id, favorites.c.item_type == item_type, favorites.c.item_id == item_id
            )
        )


def favorite_ids(conn: Connection, user_id: int, item_type: str) -> list[int]:
    """All favorite ids of one type, so the client can mark hearts in any list without a join."""
    _table(item_type)
    return [
        r[0]
        for r in conn.execute(
            select(favorites.c.item_id)
            .where(favorites.c.user_id == user_id, favorites.c.item_type == item_type)
            .order_by(favorites.c.created_at.desc())
            .limit(MAX_FAVORITE_IDS)
        )
    ]


def list_favorites(conn: Connection, user_id: int, item_type: str, limit: int, offset: int):
    """Newest first, with full item data."""
    table = _table(item_type)
    base = (
        select(favorites.c.item_id)
        .where(favorites.c.user_id == user_id, favorites.c.item_type == item_type)
        .order_by(favorites.c.created_at.desc(), favorites.c.item_id.desc())
    )
    ids = [r[0] for r in conn.execute(base.limit(limit).offset(offset))]
    total = conn.execute(
        select(func.count()).where(favorites.c.user_id == user_id, favorites.c.item_type == item_type)
    ).scalar_one()
    detail, to_item = {
        "track": (track_select(), track_item),
        "album": (album_select(), album_item),
        "artist": (artist_select(), artist_item),
    }[item_type]
    return [to_item(r) for r in fetch_ordered(conn, detail, table.c.id, ids)], total


def record_play(conn: Connection, user_id: int, track_id: int, played_ms: int) -> None:
    if conn.execute(select(tracks.c.id).where(tracks.c.id == track_id)).scalar() is None:
        raise NotFound("track not found")
    conn.execute(
        play_history.insert().values(user_id=user_id, track_id=track_id, played_at=now_ms(), played_ms=played_ms)
    )
    # Keep history bounded per user; cheap thanks to the (user_id, played_at) index.
    cutoff = conn.execute(
        select(play_history.c.played_at)
        .where(play_history.c.user_id == user_id)
        .order_by(play_history.c.played_at.desc())
        .offset(HISTORY_RETENTION)
        .limit(1)
    ).scalar()
    if cutoff is not None:
        conn.execute(delete(play_history).where(play_history.c.user_id == user_id, play_history.c.played_at <= cutoff))


def list_history(conn: Connection, user_id: int, limit: int, offset: int):
    rows = conn.execute(
        track_select()
        .add_columns(play_history.c.played_at)
        .join(play_history, play_history.c.track_id == tracks.c.id)
        .where(play_history.c.user_id == user_id)
        .order_by(play_history.c.played_at.desc(), play_history.c.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [{"played_at": r.played_at, "track": track_item(r)} for r in rows]


def recent_albums(conn: Connection, user_id: int, limit: int) -> list[dict]:
    """Albums of the most recently played tracks, distinct, newest first."""
    recent = (
        select(tracks.c.album_id, func.max(play_history.c.played_at).label("last"))
        .join(tracks, tracks.c.id == play_history.c.track_id)
        .where(play_history.c.user_id == user_id)
        .group_by(tracks.c.album_id)
        .order_by(func.max(play_history.c.played_at).desc())
        .limit(limit)
    )
    ids = [r.album_id for r in conn.execute(recent)]
    return [album_item(r) for r in fetch_ordered(conn, album_select(), albums.c.id, ids)]
