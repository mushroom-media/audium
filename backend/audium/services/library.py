"""Read access to the shared library: tracks, albums, artists, search."""

import json
import posixpath
import random

from sqlalchemy import Connection, exists, func, select

from audium.db import search
from audium.db.counts import CountCache
from audium.db.pagination import Sort, fetch_ordered, page_ids
from audium.db.schema import albums, artists, covers, favorites, library_roots, track_artists, tracks
from audium.errors import BadRequest, NotFound
from audium.scanner.fallback import disc_title, split_disc
from audium.services import view_prefs

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
_artist_fallback = covers.alias("artist_fallback")
_ALBUM_TRACK_CAP = 2000


def _pick_sort(sorts: dict[str, Sort], name: str, order: str | None) -> tuple[Sort, bool]:
    sort = sorts.get(name)
    if sort is None:
        raise BadRequest(f"sort must be one of {', '.join(sorts)}")
    desc = sort.default_desc if order is None else order == "desc"
    return sort, desc


def _year(v: int) -> int | None:
    return v or None


def _text_filter(kind: str, id_col, q: str | None) -> tuple[list, str]:
    """Conditions narrowing a list to the full-text matches of `q` (in the list's own order), and
    a part for its count-cache key. Input too short to search for leaves the list unfiltered."""
    match = search.build_match_query(q) if q else None
    if match is None:
        return [], ""
    return [search.match_filter(kind, id_col, match)], match


# --- tracks --------------------------------------------------------------------------------


def _artist_credits():
    """A track's artists as JSON, one [position, id, name] each. Per row, so every list of tracks
    can link them without a query of its own."""
    return (
        select(func.json_group_array(func.json_array(track_artists.c.position, artists.c.id, artists.c.name)))
        .select_from(track_artists.join(artists, artists.c.id == track_artists.c.artist_id))
        .where(track_artists.c.track_id == tracks.c.id)
        .correlate(tracks)
        .scalar_subquery()
        .label("artist_credits")
    )


def track_select():
    return (
        select(
            tracks.c.id,
            tracks.c.title,
            tracks.c.artist_name,
            tracks.c.artist_id,
            _artist_credits(),
            tracks.c.album_id,
            albums.c.title.label("album_title"),
            tracks.c.track_no,
            tracks.c.disc_no,
            tracks.c.year,
            tracks.c.duration_ms,
            tracks.c.codec,
            tracks.c.bitrate,
            tracks.c.rg_track_gain,
            tracks.c.rg_track_peak,
            tracks.c.rg_album_gain,
            tracks.c.rg_album_peak,
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
        "artists": [{"id": i, "name": n} for _, i, n in sorted(json.loads(r.artist_credits))]
        or [{"id": r.artist_id, "name": r.artist_name}],
        "album": r.album_title,
        "album_id": r.album_id,
        "track_no": r.track_no,
        "disc_no": r.disc_no,
        "year": _year(r.year),
        "duration_ms": r.duration_ms,
        "codec": r.codec,
        "bitrate": r.bitrate,
        "cover": r.cover,
        "replaygain": replaygain(r),
    }


def replaygain(r) -> dict | None:
    gains = {
        "track_gain": r.rg_track_gain,
        "track_peak": r.rg_track_peak,
        "album_gain": r.rg_album_gain,
        "album_peak": r.rg_album_peak,
    }
    return gains if any(v is not None for v in gains.values()) else None


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
    q: str | None = None,
):
    s, desc = _pick_sort(TRACK_SORTS, sort, order)
    base, text_key = _track_ids_base(artist_id, q)
    ids, next_cursor = page_ids(conn, base, s, desc, cursor, offset, limit)
    total = counts.count(conn, f"tracks:{artist_id}:{text_key}", base)
    return _ordered(conn, track_select(), tracks.c.id, ids, track_item), next_cursor, total


def _track_ids_base(artist_id: int | None, q: str | None):
    text_conditions, text_key = _text_filter("track", tracks.c.id, q)
    conditions = [tracks.c.missing_since.is_(None), *text_conditions]
    if artist_id is not None:
        # IN, not EXISTS: with EXISTS SQLite walks the sort index over the whole library.
        conditions.append(
            tracks.c.id.in_(select(track_artists.c.track_id).where(track_artists.c.artist_id == artist_id))
        )
    return select(tracks.c.id).where(*conditions), text_key


def track_ids(
    conn: Connection,
    *,
    sort: str = "title",
    order: str | None = None,
    artist_id: int | None = None,
    q: str | None = None,
    favorite_albums_of: int | None = None,
) -> list[int]:
    """Every id of a track list, in list order: lets the player queue (and shuffle) all of it.
    `favorite_albums_of` (a user id) keeps only the tracks of that user's favorite albums."""
    stmt = _track_pool(sort, order, artist_id, q, favorite_albums_of)
    # Plain cursor: going through SQLAlchemy's rows takes twice as long for 100k ids.
    return [r[0] for r in conn.execute(stmt).cursor.fetchall()]


def _track_pool(sort: str, order: str | None, artist_id: int | None, q: str | None, favorite_albums_of: int | None):
    s, desc = _pick_sort(TRACK_SORTS, sort, order)
    base, _ = _track_ids_base(artist_id, q)
    if favorite_albums_of is not None:
        base = base.where(
            exists().where(
                favorites.c.user_id == favorite_albums_of,
                favorites.c.item_type == "album",
                favorites.c.item_id == tracks.c.album_id,
            )
        )
    return base.order_by(*[c.desc() if desc else c.asc() for c in s.columns])


def first_track(
    conn: Connection,
    counts: CountCache,
    *,
    sort: str = "title",
    order: str | None = None,
    artist_id: int | None = None,
    q: str | None = None,
    favorite_albums_of: int | None = None,
    shuffle: bool = False,
) -> dict | None:
    """The track a list starts with (with `shuffle` a random one of it), without fetching the whole
    list: the player can start this one at once and get the rest meanwhile (see track_ids)."""
    stmt = _track_pool(sort, order, artist_id, q, favorite_albums_of)
    offset = 0
    if shuffle:
        unordered = stmt.order_by(None)
        if favorite_albums_of is None:
            base, text_key = _track_ids_base(artist_id, q)
            total = counts.count(conn, f"tracks:{artist_id}:{text_key}", base)
        else:  # favorites change without the library changing
            total = conn.execute(select(func.count()).select_from(unordered.subquery())).scalar_one()
        if not total:
            return None
        offset = random.randrange(total)
    track_id = conn.execute(stmt.limit(1).offset(offset)).scalar()
    if track_id is None:
        return None
    found = tracks_by_ids(conn, [track_id])
    return found[0] if found else None


def tracks_by_ids(conn: Connection, ids: list[int]) -> list[dict]:
    """Tracks in the order of `ids`; missing ones are left out."""
    stmt = track_select().where(tracks.c.missing_since.is_(None))
    return _ordered(conn, stmt, tracks.c.id, ids, track_item)


def get_track(conn: Connection, track_id: int) -> dict:
    row = conn.execute(
        select(
            tracks,
            _artist_credits(),
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
    item = track_item(row)
    item.update(
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


def album_select():
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
    appears_on: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    q: str | None = None,
):
    s, desc = _pick_sort(ALBUM_SORTS, sort, order)
    text_conditions, text_key = _text_filter("album", albums.c.id, q)
    conditions = [albums.c.track_count > 0, *text_conditions]
    if artist_id is not None:
        conditions.append(albums.c.album_artist_id == artist_id)
    if appears_on is not None:
        # Albums of other artists (compilations, features) with at least one track by this artist
        conditions.append(albums.c.album_artist_id != appears_on)
        conditions.append(
            exists().where(
                tracks.c.album_id == albums.c.id,
                tracks.c.missing_since.is_(None),
                track_artists.c.track_id == tracks.c.id,
                track_artists.c.artist_id == appears_on,
            )
        )
    if year_from is not None:
        conditions.append(albums.c.year >= year_from)
    if year_to is not None:
        conditions.append(albums.c.year <= year_to)
    base = select(albums.c.id).where(*conditions)
    ids, next_cursor = page_ids(conn, base, s, desc, cursor, offset, limit)
    total = counts.count(conn, f"albums:{artist_id}:{appears_on}:{year_from}:{year_to}:{text_key}", base)
    return _ordered(conn, album_select(), albums.c.id, ids, album_item), next_cursor, total


def get_album(conn: Connection, album_id: int) -> dict:
    row = conn.execute(
        album_select()
        .add_columns(_album_cover.c.color.label("cover_color"))
        .where(albums.c.id == album_id, albums.c.track_count > 0)
    ).first()
    if row is None:
        raise NotFound("album not found")
    item = album_item(row)
    item["cover_color"] = row.cover_color or None
    track_rows = conn.execute(
        track_select()
        .where(tracks.c.album_id == album_id, tracks.c.missing_since.is_(None))
        .order_by(tracks.c.disc_no.nulls_first(), tracks.c.track_no.nulls_last(), tracks.c.title_sort, tracks.c.id)
        .limit(_ALBUM_TRACK_CAP)
    ).all()
    item["tracks"] = [track_item(r) for r in track_rows]
    item["discs"] = _discs(conn, album_id)
    return item


def _discs(conn: Connection, album_id: int) -> list[dict]:
    """The discs of a multi-disc album, titled by their folder (Album/CD2 - Bonus/ -> "Bonus")
    when each disc has a folder of its own."""
    folders: dict[int, set[str]] = {}
    for r in conn.execute(
        select(tracks.c.disc_no, tracks.c.rel_path).where(
            tracks.c.album_id == album_id, tracks.c.missing_since.is_(None)
        )
    ):
        folders.setdefault(r.disc_no or 1, set()).add(posixpath.dirname(r.rel_path))
    if len(folders) < 2:
        return []
    one_each = {no: next(iter(f)) for no, f in folders.items() if len(f) == 1}
    own_folders = len(one_each) == len(folders) and len(set(one_each.values())) == len(folders)
    top = posixpath.commonpath(list(one_each.values())) if own_folders else ""
    out = []
    for no in sorted(folders):
        title = None
        if own_folders and one_each[no] != top:
            name = posixpath.basename(one_each[no])
            album_folder = posixpath.basename(top)
            if album_folder and name.casefold().startswith(album_folder.casefold()):
                name = name[len(album_folder) :]  # Album/Album CD2/
            # Artist/Album CD02/: the name is the album's, not the disc's
            title = None if split_disc(name)[1] is not None else disc_title(name.strip(" -_."))
        out.append({"disc_no": no, "title": title})
    return out


# --- artists -------------------------------------------------------------------------------


def artist_cover_column():
    """The artist's own picture, or, if the viewer wants it, the newest album cover (cover_id)."""
    return artists.c.image_id if view_prefs.artist_album_covers.get() is False else artists.c.cover_id


def artist_select():
    return (
        select(
            artists.c.id,
            artists.c.name,
            artists.c.album_count,
            artists.c.track_count,
            _artist_cover.c.hash.label("cover"),
            _artist_fallback.c.hash.label("fallback_cover"),
        )
        .outerjoin(_artist_cover, _artist_cover.c.id == artist_cover_column())
        .outerjoin(_artist_fallback, _artist_fallback.c.id == artists.c.cover_id)
    )


def artist_item(r) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "album_count": r.album_count,
        "track_count": r.track_count,
        "cover": r.cover,
        "fallback_cover": r.fallback_cover,
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
    q: str | None = None,
):
    s, desc = _pick_sort(ARTIST_SORTS, sort, order)
    text_conditions, text_key = _text_filter("artist", artists.c.id, q)
    base = select(artists.c.id).where(_artist_role(role), *text_conditions)
    ids, next_cursor = page_ids(conn, base, s, desc, cursor, offset, limit)
    total = counts.count(conn, f"artists:{role}:{text_key}", base)
    return _ordered(conn, artist_select(), artists.c.id, ids, artist_item), next_cursor, total


def _artist_role(role: str):
    if role == "album":
        return artists.c.album_count > 0
    if role == "all":
        return (artists.c.track_count > 0) | (artists.c.album_count > 0)
    raise BadRequest("role must be 'album' or 'all'")


def get_artist(conn: Connection, artist_id: int) -> dict:
    row = conn.execute(
        artist_select().where(artists.c.id == artist_id, (artists.c.track_count > 0) | (artists.c.album_count > 0))
    ).first()
    if row is None:
        raise NotFound("artist not found")
    return artist_item(row)


# --- A-Z index -----------------------------------------------------------------------------


def letter_index(conn: Connection, key, *conditions, index_hint: tuple | None = None) -> list[dict]:
    """Where each initial starts in a list sorted ascending by `key` (a *_sort column), for
    jumping to a letter: [{letter, offset}]. A-Z as letters; digits, symbols and other scripts
    are "#", at the first position one of them appears."""
    initial = func.substr(key, 1, 1)
    stmt = select(initial, func.count()).where(*conditions).group_by(initial).order_by(initial)
    if index_hint:
        stmt = stmt.with_hint(*index_hint, dialect_name="sqlite")
    rows = conn.execute(stmt)
    out: list[dict] = []
    seen: set[str] = set()
    offset = 0
    for ch, n in rows:
        letter = ch.upper() if ch and "a" <= ch <= "z" else "#"
        if letter not in seen:
            seen.add(letter)
            out.append({"letter": letter, "offset": offset})
        offset += n
    return out


def track_letters(conn: Connection, q: str | None = None) -> list[dict]:
    text_conditions, _ = _text_filter("track", tracks.c.id, q)
    # Without the hint SQLite reads the whole table (twice as slow) instead of this index.
    hint = None if text_conditions else (tracks, "INDEXED BY ix_tracks_present_title")
    return letter_index(conn, tracks.c.title_sort, tracks.c.missing_since.is_(None), *text_conditions, index_hint=hint)


def album_letters(conn: Connection, sort: str, q: str | None = None) -> list[dict]:
    keys = {"title": albums.c.title_sort, "artist": albums.c.artist_sort}
    if sort not in keys:
        raise BadRequest("letters exist for sort=title and sort=artist")
    text_conditions, _ = _text_filter("album", albums.c.id, q)
    return letter_index(conn, keys[sort], albums.c.track_count > 0, *text_conditions)


def artist_letters(conn: Connection, role: str, q: str | None = None) -> list[dict]:
    text_conditions, _ = _text_filter("artist", artists.c.id, q)
    return letter_index(conn, artists.c.name_sort, _artist_role(role), *text_conditions)


# --- search --------------------------------------------------------------------------------

SEARCH_TYPES = ("track", "album", "artist")


def search_all(conn: Connection, q: str, types: list[str], limit: int, offset: int = 0) -> dict:
    match = search.build_match_query(q)
    result: dict = {"tracks": [], "albums": [], "artists": []}
    if match is None:
        return result
    if "artist" in types:
        ids = search.search_ids(conn, "artist", match, limit, offset)
        result["artists"] = _ordered(conn, artist_select(), artists.c.id, ids, artist_item)
    if "album" in types:
        ids = search.search_ids(conn, "album", match, limit, offset)
        result["albums"] = _ordered(conn, album_select(), albums.c.id, ids, album_item)
    if "track" in types:
        ids = search.search_ids(conn, "track", match, limit, offset)
        result["tracks"] = _ordered(conn, track_select(), tracks.c.id, ids, track_item)
    return result


def _ordered(conn: Connection, stmt, id_col, ids: list[int], to_item) -> list[dict]:
    return [to_item(r) for r in fetch_ordered(conn, stmt, id_col, ids)]
