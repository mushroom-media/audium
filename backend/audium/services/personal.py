"""Per-user data: favorites and listening history. Always scoped to the requesting user."""

from sqlalchemy import Connection, delete, func, select, update

from audium.db.dialect import insert_for
from audium.db.pagination import fetch_ordered
from audium.db.schema import albums, artists, favorites, play_history, tracks
from audium.errors import BadRequest, Forbidden, NotFound
from audium.services import auto as auto_service
from audium.services.library import album_item, album_select, artist_item, artist_select, track_item, track_select
from audium.services.permissions import require_playlist
from audium.services.playlists import playlist_out
from audium.services.users import User
from audium.util import now_ms

ITEM_TYPES = {"track": tracks, "album": albums, "artist": artists}
MAX_FAVORITE_IDS = 50_000
HISTORY_RETENTION = 10_000  # entries per user
RECENT_SCAN = 500  # history entries looked at for "recently played"
# Where a track was played from, as sent by the client and stored in play_history.context.
CONTEXT_PATTERN = r"^((album|playlist|auto):\d{1,12}|favorites|radio:(track|album|artist):\d{1,12})$"


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


def record_play(
    conn: Connection,
    user_id: int,
    track_id: int,
    played_ms: int,
    context: str | None = None,
    *,
    listened_ms: int | None = None,
    client: str | None = None,
    played_at: int | None = None,
) -> int:
    """`listened_ms`: the time it really sounded so far (None: not measured, e.g. Subsonic apps;
    see set_listened); `client`: the app that reported it (Subsonic); `played_at`: when, for plays
    an app reports later (offline listening). Never in the future. Returns the play's id."""
    duration = conn.execute(select(tracks.c.duration_ms).where(tracks.c.id == track_id)).scalar()
    if duration is None:
        raise NotFound("track not found")
    now = now_ms()
    play_id = conn.execute(
        play_history.insert().values(
            user_id=user_id,
            track_id=track_id,
            played_at=min(played_at, now) if played_at else now,
            played_ms=played_ms,
            context=context,
            client=client,
            listened_ms=None if listened_ms is None else _cap(listened_ms, duration),
        )
    ).inserted_primary_key[0]
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
    return play_id


def _cap(listened_ms: int, duration_ms: int) -> int:
    """A play never sounds longer than its track (a client clock running wild, say)."""
    return min(listened_ms, duration_ms) if duration_ms > 0 else listened_ms


def set_listened(conn: Connection, user_id: int, play_id: int, listened_ms: int) -> None:
    """The final listened time of a play, reported when the track stops (next track, skip, closing
    the tab). Only grows: a late or repeated report never takes time away."""
    row = conn.execute(
        select(play_history.c.listened_ms, tracks.c.duration_ms)
        .join(tracks, tracks.c.id == play_history.c.track_id)
        .where(play_history.c.id == play_id, play_history.c.user_id == user_id)
    ).one_or_none()
    if row is None:
        raise NotFound("play not found")
    value = max(row.listened_ms or 0, _cap(listened_ms, row.duration_ms))
    conn.execute(update(play_history).where(play_history.c.id == play_id).values(listened_ms=value))


def list_history(conn: Connection, user_id: int, limit: int, offset: int):
    rows = conn.execute(
        track_select()
        .add_columns(play_history.c.played_at, play_history.c.client)
        .join(play_history, play_history.c.track_id == tracks.c.id)
        .where(play_history.c.user_id == user_id)
        .order_by(play_history.c.played_at.desc(), play_history.c.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [{"played_at": r.played_at, "client": r.client, "track": track_item(r)} for r in rows]


def listening_stats(conn: Connection, user_id: int, since: int | None, limit: int) -> dict:
    """Plays since `since` (ms; None = all of the history): how many, roughly how long, and the
    most played tracks, albums and artists (artists ranked by listening time, the rest by plays).
    The time is what the plays really sounded (listened_ms, measured by the web player without
    pauses, buffering or skipped parts); plays without a measurement (from before migration 0013,
    Subsonic apps) count with the track's length, as all plays did before."""
    cond = [play_history.c.user_id == user_id]
    if since is not None:
        cond.append(play_history.c.played_at >= since)
    listened = func.coalesce(play_history.c.listened_ms, tracks.c.duration_ms).label("listened_ms")
    plays = select(play_history.c.played_at, tracks.c.id, tracks.c.album_id, tracks.c.artist_id, listened)
    plays = plays.join(tracks, tracks.c.id == play_history.c.track_id).where(*cond).subquery()
    count, ms = conn.execute(select(func.count(), func.coalesce(func.sum(plays.c.listened_ms), 0))).one()

    def top(col, detail, id_col, to_item, key, by_time=False):
        n = func.count().label("n")
        ms = func.coalesce(func.sum(plays.c.listened_ms), 0).label("ms")
        order = (ms.desc(), n.desc()) if by_time else (n.desc(),)
        ranked = conn.execute(
            select(col, n, ms).group_by(col).order_by(*order, func.max(plays.c.played_at).desc()).limit(limit)
        ).all()
        counts = {r[0]: (r.n, int(r.ms)) for r in ranked}
        rows = fetch_ordered(conn, detail, id_col, list(counts))
        return [{key: to_item(r), "plays": counts[r.id][0], "listening_ms": counts[r.id][1]} for r in rows]

    return {
        "since": since,
        "plays": count,
        "listening_ms": int(ms),
        "tracks": top(plays.c.id, track_select(), tracks.c.id, track_item, "track"),
        "albums": top(plays.c.album_id, album_select(), albums.c.id, album_item, "album"),
        "artists": top(plays.c.artist_id, artist_select(), artists.c.id, artist_item, "artist", by_time=True),
    }


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


def recently_played(conn: Connection, user: User, limit: int) -> list[dict]:
    """What was played recently, one entry per source, newest first: the album, playlist or radio
    the tracks were played from. Tracks played from elsewhere (search, an artist) count for their album;
    sources that are gone or no longer visible are skipped."""
    rows = conn.execute(
        select(play_history.c.context, tracks.c.album_id)
        .join(tracks, tracks.c.id == play_history.c.track_id)
        .where(play_history.c.user_id == user.id)
        .order_by(play_history.c.played_at.desc(), play_history.c.id.desc())
        .limit(RECENT_SCAN)
    )
    out, seen = [], set()
    for r in rows:
        key = r.context or f"album:{r.album_id}"
        if key in seen:
            continue
        seen.add(key)
        item = _source(conn, user, key)
        if item is not None:
            out.append(item)
            if len(out) >= limit:
                break
    return out


def _source(conn: Connection, user: User, key: str) -> dict | None:
    kind, _, rest = key.partition(":")
    radio_of = None
    if kind == "radio":
        radio_of, _, rest = rest.partition(":")
    ref = int(rest) if rest.isdigit() else None
    item = {"type": kind, "id": ref, "radio_of": radio_of, "subtitle": None, "cover": None, "cover_preset": None}
    if kind == "favorites":
        return item | {"name": "Lieblingssongs", "subtitle": "Playlist"}
    if ref is None:
        return None
    if kind == "album" or radio_of == "album":
        row = conn.execute(album_select().where(albums.c.id == ref)).first()
        if row is None:
            return None
        return item | {"name": row.title, "subtitle": "Radio" if radio_of else row.artist_name, "cover": row.cover}
    if kind == "playlist":
        try:
            row, role = require_playlist(conn, user, ref, "view")
        except (NotFound, Forbidden):
            return None
        pl = playlist_out(conn, row, role)
        sub = "Playlist" if role == "owner" else f"von {pl['owner']['display_name']}"
        return item | {"name": pl["name"], "subtitle": sub, "cover": pl["cover"], "cover_preset": pl["cover_preset"]}
    if kind == "auto":
        try:
            auto = auto_service.get_auto(conn, user, ref)
        except NotFound:
            return None
        return item | {"name": auto["name"], "subtitle": "Playlist", "cover": auto["cover"]}
    if radio_of == "track":
        row = conn.execute(track_select().where(tracks.c.id == ref)).first()
        name = row and row.title
    elif radio_of == "artist":
        row = conn.execute(artist_select().where(artists.c.id == ref)).first()
        name = row and row.name
    else:
        return None
    # A station always gets a picture, whatever the artist setting (tracks have no fallback column).
    cover = getattr(row, "fallback_cover", None) or (row and row.cover)
    return None if row is None else item | {"name": name, "subtitle": "Radio", "cover": cover}
