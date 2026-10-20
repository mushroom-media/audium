"""Read access to the shared library: tracks, albums, artists, search."""

from sqlalchemy import Connection, exists, select

from audium.db import search
from audium.db.counts import CountCache
from audium.db.pagination import Sort, fetch_ordered, page_ids
from audium.db.schema import albums, artists, covers, library_roots, track_artists, tracks
from audium.errors import BadRequest, NotFound

TRACK_SORTS = {
    "title": Sort("title", (tracks.c.title_sort, tracks.c.id)),
    "added": Sort("added", (tracks.c.added_at, tracks.c.id), default_desc=True),
    "year": Sort("year", (tracks.c.year, tracks.c.id), default_desc=True),
}
ALBUM_SORTS = {
    "title": Sort("title", (albums.c.title_sort, albums.c.id)),
    "artist": Sort("artist", (albums.c.artist_sort, albums.c.year, albums.c.id)),
    "year": Sort("year", (albums.c.year, albums.c.id), default_desc=True),
    "added": Sort("added", (albums.c.added_at, albums.c.id), default_desc=True),
}
ARTIST_SORTS = {"name": Sort("name", (artists.c.name_sort, artists.c.id))}

_album_artist = artists.alias("album_artist")
_album_cover = covers.alias("album_cover")
_artist_cover = covers.alias("artist_cover")
_ALBUM_TRACK_CAP = 2000


def _pick_sort(sorts: dict[str, Sort], name: str, order: str | None) -> tuple[Sort, bool]:
    sort = sorts.get(name)
    if sort is None:
        raise BadRequest(f"sort must be one of {', '.join(sorts)}")
    desc = sort.default_desc if order is None else order == "desc"
    return sort, desc


def _year(v: int) -> int | None:
    return v or None


# --- tracks --------------------------------------------------------------------------------


def _track_select():
    return (
        select(
            tracks.c.id,
            tracks.c.title,
            tracks.c.artist_name,
            tracks.c.artist_id,
            tracks.c.album_id,
            albums.c.title.label("album_title"),
            tracks.c.track_no,
            tracks.c.disc_no,
            tracks.c.year,
            tracks.c.duration_ms,
            tracks.c.codec,
            tracks.c.bitrate,
            covers.c.hash.label("cover"),
        )
        .join(albums, albums.c.id == tracks.c.album_id)
        .outerjoin(covers, covers.c.id == tracks.c.cover_id)
    )


def track_item(r) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "artist": r.artist_name,
        "artist_id": r.artist_id,
        "album": r.album_title,
        "album_id": r.album_id,
        "track_no": r.track_no,
        "disc_no": r.disc_no,
        "year": _year(r.year),
        "duration_ms": r.duration_ms,
        "codec": r.codec,
        "bitrate": r.bitrate,
        "cover": r.cover,
    }


def list_tracks(
    conn: Connection,
    counts: CountCache,
    *,
    sort: str = "title",
    order: str | None = None,
    cursor: str | None = None,
    offset: int = 0,
    limit: int = 100,
    artist_id: int | None = None,
):
    s, desc = _pick_sort(TRACK_SORTS, sort, order)
    conditions = [tracks.c.missing_since.is_(None)]
    if artist_id is not None:
        conditions.append(
            exists().where(track_artists.c.track_id == tracks.c.id, track_artists.c.artist_id == artist_id)
        )
    base = select(tracks.c.id).where(*conditions)
    ids, next_cursor = page_ids(conn, base, s, desc, cursor, offset, limit)
    total = counts.count(conn, f"tracks:{artist_id}", base)
    return _ordered(conn, _track_select(), tracks.c.id, ids, track_item), next_cursor, total


def get_track(conn: Connection, track_id: int) -> dict:
    row = conn.execute(
        select(
            tracks,
            albums.c.title.label("album_title"),
            covers.c.hash.label("cover"),
            library_roots.c.path.label("root_path"),
        )
        .join(albums, albums.c.id == tracks.c.album_id)
        .join(library_roots, library_roots.c.id == tracks.c.root_id)
        .outerjoin(covers, covers.c.id == tracks.c.cover_id)
        .where(tracks.c.id == track_id, tracks.c.missing_since.is_(None))
    ).first()
    if row is None:
        raise NotFound("track not found")
    track_artist_rows = conn.execute(
        select(artists.c.id, artists.c.name)
        .join(track_artists, track_artists.c.artist_id == artists.c.id)
        .where(track_artists.c.track_id == track_id)
        .order_by(track_artists.c.position)
    ).all()
    item = track_item(row)
    item.update(
        artists=[{"id": a.id, "name": a.name} for a in track_artist_rows],
        path=row.rel_path,
        root_id=row.root_id,
        size=row.size,
        container=row.container,
        sample_rate=row.sample_rate,
        bit_depth=row.bit_depth,
        channels=row.channels,
        date=row.date,
        genre=row.genre_raw,
        mb_recording_id=row.mb_recording_id,
        mb_track_id=row.mb_track_id,
        replaygain={
            "track_gain": row.rg_track_gain,
            "track_peak": row.rg_track_peak,
            "album_gain": row.rg_album_gain,
            "album_peak": row.rg_album_peak,
        },
        tag_status=row.tag_status,
        added_at=row.added_at,
    )
    return item


# --- albums --------------------------------------------------------------------------------


def _album_select():
    return (
        select(
            albums.c.id,
            albums.c.title,
            albums.c.album_artist_id,
            _album_artist.c.name.label("artist_name"),
            albums.c.year,
            albums.c.track_count,
            albums.c.duration_ms,
            albums.c.compilation,
            albums.c.added_at,
            _album_cover.c.hash.label("cover"),
        )
        .join(_album_artist, _album_artist.c.id == albums.c.album_artist_id)
        .outerjoin(_album_cover, _album_cover.c.id == albums.c.cover_id)
    )


def album_item(r) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "artist": r.artist_name,
        "artist_id": r.album_artist_id,
        "year": _year(r.year),
        "track_count": r.track_count,
        "duration_ms": r.duration_ms,
        "compilation": bool(r.compilation),
        "added_at": r.added_at,
        "cover": r.cover,
    }


def list_albums(
    conn: Connection,
    counts: CountCache,
    *,
    sort: str = "title",
    order: str | None = None,
    cursor: str | None = None,
    offset: int = 0,
    limit: int = 100,
    artist_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
):
    s, desc = _pick_sort(ALBUM_SORTS, sort, order)
    conditions = [albums.c.track_count > 0]
    if artist_id is not None:
        conditions.append(albums.c.album_artist_id == artist_id)
    if year_from is not None:
        conditions.append(albums.c.year >= year_from)
    if year_to is not None:
        conditions.append(albums.c.year <= year_to)
    base = select(albums.c.id).where(*conditions)
    ids, next_cursor = page_ids(conn, base, s, desc, cursor, offset, limit)
    total = counts.count(conn, f"albums:{artist_id}:{year_from}:{year_to}", base)
    return _ordered(conn, _album_select(), albums.c.id, ids, album_item), next_cursor, total


def get_album(conn: Connection, album_id: int) -> dict:
    row = conn.execute(_album_select().where(albums.c.id == album_id, albums.c.track_count > 0)).first()
    if row is None:
        raise NotFound("album not found")
    item = album_item(row)
    track_rows = conn.execute(
        _track_select()
        .where(tracks.c.album_id == album_id, tracks.c.missing_since.is_(None))
        .order_by(tracks.c.disc_no.nulls_first(), tracks.c.track_no.nulls_last(), tracks.c.title_sort, tracks.c.id)
        .limit(_ALBUM_TRACK_CAP)
    ).all()
    item["tracks"] = [track_item(r) for r in track_rows]
    return item


# --- artists -------------------------------------------------------------------------------


def _artist_select():
    return select(
        artists.c.id,
        artists.c.name,
        artists.c.album_count,
        artists.c.track_count,
        _artist_cover.c.hash.label("cover"),
    ).outerjoin(_artist_cover, _artist_cover.c.id == artists.c.cover_id)


def artist_item(r) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "album_count": r.album_count,
        "track_count": r.track_count,
        "cover": r.cover,
    }


def list_artists(
    conn: Connection,
    counts: CountCache,
    *,
    sort: str = "name",
    order: str | None = None,
    cursor: str | None = None,
    offset: int = 0,
    limit: int = 100,
    role: str = "album",
):
    s, desc = _pick_sort(ARTIST_SORTS, sort, order)
    if role == "album":
        cond = artists.c.album_count > 0
    elif role == "all":
        cond = (artists.c.track_count > 0) | (artists.c.album_count > 0)
    else:
        raise BadRequest("role must be 'album' or 'all'")
    base = select(artists.c.id).where(cond)
    ids, next_cursor = page_ids(conn, base, s, desc, cursor, offset, limit)
    total = counts.count(conn, f"artists:{role}", base)
    return _ordered(conn, _artist_select(), artists.c.id, ids, artist_item), next_cursor, total


def get_artist(conn: Connection, artist_id: int) -> dict:
    row = conn.execute(
        _artist_select().where(artists.c.id == artist_id, (artists.c.track_count > 0) | (artists.c.album_count > 0))
    ).first()
    if row is None:
        raise NotFound("artist not found")
    return artist_item(row)


# --- search --------------------------------------------------------------------------------

SEARCH_TYPES = ("track", "album", "artist")


def search_all(conn: Connection, q: str, types: list[str], limit: int, offset: int = 0) -> dict:
    match = search.build_match_query(q)
    result: dict = {"tracks": [], "albums": [], "artists": []}
    if match is None:
        return result
    if "artist" in types:
        ids = search.search_ids(conn, "artist", match, limit, offset)
        result["artists"] = _ordered(conn, _artist_select(), artists.c.id, ids, artist_item)
    if "album" in types:
        ids = search.search_ids(conn, "album", match, limit, offset)
        result["albums"] = _ordered(conn, _album_select(), albums.c.id, ids, album_item)
    if "track" in types:
        ids = search.search_ids(conn, "track", match, limit, offset)
        result["tracks"] = _ordered(conn, _track_select(), tracks.c.id, ids, track_item)
    return result


def _ordered(conn: Connection, stmt, id_col, ids: list[int], to_item) -> list[dict]:
    return [to_item(r) for r in fetch_ordered(conn, stmt, id_col, ids)]
