"""Library reads with every detail third-party clients (the Subsonic API) show: file format and
quality, genres, per-user play counts and favorites, album lists and random picks.

Like services/library.py these only see present tracks and non-empty albums. Functions that
take `ids` return rows in the order of `ids`; batches of extras (genres, favorites, play counts)
are one query per list, never one per item.
"""

import random
from collections.abc import Iterable

from sqlalchemy import Connection, and_, exists, func, literal, select

from audium.analysis.genres import slug
from audium.db.pagination import fetch_ordered
from audium.db.schema import (
    albums,
    artists,
    covers,
    favorites,
    genres,
    library_roots,
    play_history,
    track_artists,
    track_genres,
    tracks,
)
from audium.util import norm

_album_artist = artists.alias("album_artist")
_album_cover = covers.alias("album_cover")
_artist_cover = covers.alias("artist_cover")
_CHUNK = 500

ALBUM_LIST_TYPES = (
    "random",
    "newest",
    "highest",
    "frequent",
    "recent",
    "alphabeticalByName",
    "alphabeticalByArtist",
    "starred",
    "byYear",
    "byGenre",
)


def _chunks(ids: list[int]) -> Iterable[list[int]]:
    for i in range(0, len(ids), _CHUNK):
        yield ids[i : i + _CHUNK]


# --- rows ----------------------------------------------------------------------------------


def song_select():
    return (
        select(
            tracks.c.id,
            tracks.c.root_id,
            tracks.c.rel_path,
            tracks.c.size,
            tracks.c.container,
            tracks.c.codec,
            tracks.c.bitrate,
            tracks.c.sample_rate,
            tracks.c.bit_depth,
            tracks.c.channels,
            tracks.c.duration_ms,
            tracks.c.title,
            tracks.c.title_sort,
            tracks.c.artist_name,
            tracks.c.artist_id,
            tracks.c.album_id,
            albums.c.title.label("album_title"),
            albums.c.album_artist_id,
            tracks.c.track_no,
            tracks.c.disc_no,
            tracks.c.year,
            tracks.c.mb_recording_id,
            tracks.c.rg_track_gain,
            tracks.c.rg_track_peak,
            tracks.c.rg_album_gain,
            tracks.c.rg_album_peak,
            tracks.c.added_at,
            covers.c.hash.label("cover"),
        )
        .join(albums, albums.c.id == tracks.c.album_id)
        .outerjoin(covers, covers.c.id == tracks.c.cover_id)
        .where(tracks.c.missing_since.is_(None))
    )


def songs(conn: Connection, ids: list[int]) -> list:
    out = {}
    for chunk in _chunks(ids):
        out.update((r.id, r) for r in conn.execute(song_select().where(tracks.c.id.in_(chunk))))
    return [out[i] for i in ids if i in out]


def album_select():
    return (
        select(
            albums.c.id,
            albums.c.title,
            albums.c.title_sort,
            albums.c.album_artist_id,
            _album_artist.c.name.label("artist_name"),
            albums.c.year,
            albums.c.compilation,
            albums.c.mb_release_id,
            albums.c.track_count,
            albums.c.duration_ms,
            albums.c.added_at,
            _album_cover.c.hash.label("cover"),
        )
        .join(_album_artist, _album_artist.c.id == albums.c.album_artist_id)
        .outerjoin(_album_cover, _album_cover.c.id == albums.c.cover_id)
        .where(albums.c.track_count > 0)
    )


def album_rows(conn: Connection, ids: list[int]) -> list:
    out = []
    for chunk in _chunks(ids):
        out += fetch_ordered(conn, album_select(), albums.c.id, chunk)
    return out


def artist_select():
    return (
        select(
            artists.c.id,
            artists.c.name,
            artists.c.name_sort,
            artists.c.mb_artist_id,
            artists.c.album_count,
            artists.c.track_count,
            _artist_cover.c.hash.label("cover"),
        )
        .outerjoin(_artist_cover, _artist_cover.c.id == artists.c.cover_id)
        .where((artists.c.track_count > 0) | (artists.c.album_count > 0))
    )


def artist_rows(conn: Connection, ids: list[int]) -> list:
    out = []
    for chunk in _chunks(ids):
        out += fetch_ordered(conn, artist_select(), artists.c.id, chunk)
    return out


def find_artist_by_name(conn: Connection, name: str):
    return conn.execute(artist_select().where(artists.c.name_norm == norm(name.strip()))).first()


# --- extras per batch ----------------------------------------------------------------------


def track_genres_of(conn: Connection, ids: list[int]) -> dict[int, list[str]]:
    """Genre names per track: tagged ones first, then detected ones by weight."""
    out: dict[int, list[str]] = {}
    for chunk in _chunks(ids):
        rows = conn.execute(
            select(track_genres.c.track_id, genres.c.name)
            .join(genres, genres.c.id == track_genres.c.genre_id)
            .where(track_genres.c.track_id.in_(chunk))
            .order_by(track_genres.c.track_id, (track_genres.c.source == "tag").desc(), track_genres.c.weight.desc())
        )
        for track_id, name in rows:
            out.setdefault(track_id, []).append(name)
    return out


def album_genres_of(conn: Connection, ids: list[int]) -> dict[int, list[str]]:
    """Genre names per album, the most common among its tracks first."""
    out: dict[int, list[str]] = {}
    n = func.count().label("n")
    for chunk in _chunks(ids):
        rows = conn.execute(
            select(tracks.c.album_id, genres.c.name, n)
            .join(track_genres, track_genres.c.track_id == tracks.c.id)
            .join(genres, genres.c.id == track_genres.c.genre_id)
            .where(tracks.c.album_id.in_(chunk), tracks.c.missing_since.is_(None))
            .group_by(tracks.c.album_id, genres.c.id, genres.c.name)
            .order_by(tracks.c.album_id, n.desc(), genres.c.name)
        )
        for album_id, name, _n in rows:
            out.setdefault(album_id, []).append(name)
    return out


def track_artists_of(conn: Connection, ids: list[int]) -> dict[int, list[tuple[int, str]]]:
    out: dict[int, list[tuple[int, str]]] = {}
    for chunk in _chunks(ids):
        rows = conn.execute(
            select(track_artists.c.track_id, artists.c.id, artists.c.name)
            .join(artists, artists.c.id == track_artists.c.artist_id)
            .where(track_artists.c.track_id.in_(chunk))
            .order_by(track_artists.c.track_id, track_artists.c.position)
        )
        for track_id, artist_id, name in rows:
            out.setdefault(track_id, []).append((artist_id, name))
    return out


def album_artist_of(conn: Connection, ids: list[int]) -> dict[int, int]:
    """Album artist per track."""
    out: dict[int, int] = {}
    for chunk in _chunks(ids):
        rows = conn.execute(
            select(tracks.c.id, albums.c.album_artist_id)
            .join(albums, albums.c.id == tracks.c.album_id)
            .where(tracks.c.id.in_(chunk))
        )
        out.update((k, v) for k, v in rows)
    return out


def favorite_times(conn: Connection, user_id: int, item_type: str, ids: list[int]) -> dict[int, int]:
    """When the user starred each of `ids` (only those that are favorites)."""
    out: dict[int, int] = {}
    for chunk in _chunks(ids):
        rows = conn.execute(
            select(favorites.c.item_id, favorites.c.created_at).where(
                favorites.c.user_id == user_id, favorites.c.item_type == item_type, favorites.c.item_id.in_(chunk)
            )
        )
        out.update((k, v) for k, v in rows)
    return out


def play_stats(conn: Connection, user_id: int, ids: list[int]) -> dict[int, tuple[int, int]]:
    """(play count, last played) of the user per track."""
    out: dict[int, tuple[int, int]] = {}
    for chunk in _chunks(ids):
        rows = conn.execute(
            select(play_history.c.track_id, func.count(), func.max(play_history.c.played_at))
            .where(play_history.c.user_id == user_id, play_history.c.track_id.in_(chunk))
            .group_by(play_history.c.track_id)
        )
        out.update((t, (n, last)) for t, n, last in rows)
    return out


def album_play_stats(conn: Connection, user_id: int, ids: list[int]) -> dict[int, tuple[int, int]]:
    out: dict[int, tuple[int, int]] = {}
    for chunk in _chunks(ids):
        rows = conn.execute(
            select(tracks.c.album_id, func.count(), func.max(play_history.c.played_at))
            .join(tracks, tracks.c.id == play_history.c.track_id)
            .where(play_history.c.user_id == user_id, tracks.c.album_id.in_(chunk))
            .group_by(tracks.c.album_id)
        )
        out.update((a, (n, last)) for a, n, last in rows)
    return out


def cover_of(conn: Connection, kind: str, item_id: int) -> str | None:
    """Cover hash of a track (else its album's), an album, or an artist (else one of its
    albums')."""
    if kind == "track":
        row = conn.execute(
            select(covers.c.hash, _album_cover.c.hash.label("album_cover"))
            .select_from(tracks)
            .join(albums, albums.c.id == tracks.c.album_id)
            .outerjoin(covers, covers.c.id == tracks.c.cover_id)
            .outerjoin(_album_cover, _album_cover.c.id == albums.c.cover_id)
            .where(tracks.c.id == item_id, tracks.c.missing_since.is_(None))
        ).first()
        return (row.hash or row.album_cover) if row else None
    if kind == "album":
        return conn.execute(
            select(covers.c.hash).join(albums, albums.c.cover_id == covers.c.id).where(albums.c.id == item_id)
        ).scalar()
    own = conn.execute(
        select(covers.c.hash).join(artists, artists.c.cover_id == covers.c.id).where(artists.c.id == item_id)
    ).scalar()
    if own:
        return own
    return conn.execute(
        select(covers.c.hash)
        .join(albums, albums.c.cover_id == covers.c.id)
        .where(albums.c.album_artist_id == item_id, albums.c.track_count > 0)
        .order_by(albums.c.year.desc(), albums.c.id)
        .limit(1)
    ).scalar()


# --- folders (library roots) ---------------------------------------------------------------


def music_folders(conn: Connection) -> list:
    return conn.execute(
        select(library_roots.c.id, library_roots.c.path)
        .where(library_roots.c.enabled.is_(True))
        .order_by(library_roots.c.path)
    ).all()


def _album_in_root(root_id: int):
    return exists().where(
        tracks.c.album_id == albums.c.id, tracks.c.root_id == root_id, tracks.c.missing_since.is_(None)
    )


def _artist_in_root(root_id: int):
    return exists().where(albums.c.album_artist_id == artists.c.id, albums.c.track_count > 0, _album_in_root(root_id))


def present_track_count(conn: Connection) -> int:
    return conn.execute(select(func.count()).where(tracks.c.missing_since.is_(None))).scalar_one()


def last_modified(conn: Connection) -> int:
    """When the library last changed (last finished scan), for getIndexes."""
    return conn.execute(select(func.coalesce(func.max(library_roots.c.last_scan_at), 0))).scalar_one()


# --- browsing ------------------------------------------------------------------------------


def album_artists(conn: Connection, root_id: int | None = None) -> list:
    """All album artists, sorted, for the A-Z index."""
    stmt = artist_select().where(artists.c.album_count > 0)
    if root_id is not None:
        stmt = stmt.where(_artist_in_root(root_id))
    return conn.execute(stmt.order_by(artists.c.name_sort, artists.c.id)).all()


def albums_of_artist(conn: Connection, artist_id: int) -> list:
    return conn.execute(
        album_select().where(albums.c.album_artist_id == artist_id).order_by(albums.c.year, albums.c.title_sort)
    ).all()


def album_track_ids(conn: Connection, album_id: int) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            select(tracks.c.id)
            .where(tracks.c.album_id == album_id, tracks.c.missing_since.is_(None))
            .order_by(tracks.c.disc_no.nulls_first(), tracks.c.track_no.nulls_last(), tracks.c.title_sort, tracks.c.id)
        )
    ]


def artist_track_ids(conn: Connection, artist_id: int, limit: int = 5000) -> list[int]:
    """Tracks the artist plays on (as main or featured artist)."""
    return [
        r[0]
        for r in conn.execute(
            select(tracks.c.id)
            .join(track_artists, track_artists.c.track_id == tracks.c.id)
            .where(track_artists.c.artist_id == artist_id, tracks.c.missing_since.is_(None))
            .distinct()
            .limit(limit)
        )
    ]


def album_list(
    conn: Connection,
    user_id: int,
    kind: str,
    size: int,
    offset: int,
    *,
    from_year: int | None = None,
    to_year: int | None = None,
    genre: str | None = None,
    root_id: int | None = None,
) -> list[int]:
    """Album ids for one of the Subsonic list types (ALBUM_LIST_TYPES)."""
    stmt = select(albums.c.id).where(albums.c.track_count > 0)
    if root_id is not None:
        stmt = stmt.where(_album_in_root(root_id))
    if kind == "random":
        stmt = stmt.order_by(func.random())
    elif kind == "newest":
        stmt = stmt.order_by(albums.c.added_at.desc(), albums.c.id.desc())
    elif kind == "alphabeticalByName":
        stmt = stmt.order_by(albums.c.title_sort, albums.c.id)
    elif kind == "alphabeticalByArtist":
        stmt = stmt.order_by(albums.c.artist_sort, albums.c.year, albums.c.id)
    elif kind == "byYear":
        lo, hi = from_year or 0, to_year if to_year is not None else 9999
        desc = lo > hi  # fromYear > toYear: newest first (Subsonic spec)
        lo, hi = min(lo, hi), max(lo, hi)
        stmt = stmt.where(albums.c.year >= lo, albums.c.year <= hi, albums.c.year > 0)
        year = albums.c.year.desc() if desc else albums.c.year.asc()
        stmt = stmt.order_by(year, albums.c.title_sort, albums.c.id)
    elif kind == "byGenre":
        genre_id = genre_id_by_name(conn, genre or "")
        if genre_id is None:
            return []
        in_genre = exists().where(
            tracks.c.album_id == albums.c.id,
            tracks.c.missing_since.is_(None),
            track_genres.c.track_id == tracks.c.id,
            track_genres.c.genre_id == genre_id,
        )
        stmt = stmt.where(in_genre).order_by(albums.c.title_sort, albums.c.id)
    elif kind == "starred":
        stmt = stmt.join(
            favorites,
            and_(favorites.c.item_id == albums.c.id, favorites.c.item_type == "album", favorites.c.user_id == user_id),
        ).order_by(favorites.c.created_at.desc(), albums.c.id)
    elif kind in ("frequent", "recent"):
        plays = (
            select(
                tracks.c.album_id.label("album_id"),
                func.count().label("n"),
                func.max(play_history.c.played_at).label("last"),
            )
            .join(tracks, tracks.c.id == play_history.c.track_id)
            .where(play_history.c.user_id == user_id)
            .group_by(tracks.c.album_id)
            .subquery()
        )
        stmt = stmt.join(plays, plays.c.album_id == albums.c.id)
        key = plays.c.n.desc() if kind == "frequent" else plays.c.last.desc()
        stmt = stmt.order_by(key, plays.c.last.desc(), albums.c.id)
    elif kind == "highest":
        return []  # audium has no ratings (yet), see docs/subsonic.md
    else:
        raise ValueError(kind)
    return [r[0] for r in conn.execute(stmt.limit(size).offset(offset))]


def random_track_ids(
    conn: Connection,
    n: int,
    *,
    genre: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    root_id: int | None = None,
) -> list[int]:
    conditions = [tracks.c.missing_since.is_(None)]
    if genre:
        genre_id = genre_id_by_name(conn, genre)
        if genre_id is None:
            return []
        conditions.append(exists().where(track_genres.c.track_id == tracks.c.id, track_genres.c.genre_id == genre_id))
    if from_year is not None:
        conditions.append(tracks.c.year >= from_year)
    if to_year is not None:
        conditions.append(tracks.c.year <= to_year)
    if root_id is not None:
        conditions.append(tracks.c.root_id == root_id)
    if len(conditions) == 1:
        sampled = _sample_ids(conn, n)
        if sampled is not None:
            return sampled
    return [r[0] for r in conn.execute(select(tracks.c.id).where(*conditions).order_by(func.random()).limit(n))]


def _sample_ids(conn: Connection, n: int) -> list[int] | None:
    """n random present tracks by drawing random ids: ORDER BY random() reads the whole table,
    which costs ~100 ms at 100k tracks. None when the ids are too sparse for this to work."""
    lo, hi = conn.execute(select(func.min(tracks.c.id), func.max(tracks.c.id))).one()
    if lo is None:
        return []
    present = conn.execute(select(func.count()).where(tracks.c.missing_since.is_(None))).scalar_one()
    if present <= n * 4:
        return None  # small library: the plain query is cheap and exact
    rng = random.SystemRandom()
    found: list[int] = []
    seen: set[int] = set()
    for _ in range(6):
        want = (n - len(found)) * 3
        candidates = [c for c in {rng.randint(lo, hi) for _ in range(want)} if c not in seen]
        seen.update(candidates)
        for chunk in _chunks(candidates):
            found += [
                r[0]
                for r in conn.execute(
                    select(tracks.c.id).where(tracks.c.id.in_(chunk), tracks.c.missing_since.is_(None))
                )
            ]
        if len(found) >= n:
            break
    if len(found) < n:
        return None
    rng.shuffle(found)
    return found[:n]


# --- genres --------------------------------------------------------------------------------


def genre_id_by_name(conn: Connection, name: str) -> int | None:
    return conn.execute(select(genres.c.id).where(genres.c.slug == slug(name.strip()))).scalar()


def genre_counts(conn: Connection) -> list:
    """(name, song count, album count) of every genre with present tracks, by name."""
    return conn.execute(
        select(
            genres.c.name,
            func.count().label("songs"),
            func.count(tracks.c.album_id.distinct()).label("albums"),
        )
        .join(track_genres, track_genres.c.genre_id == genres.c.id)
        .join(tracks, tracks.c.id == track_genres.c.track_id)
        .where(tracks.c.missing_since.is_(None))
        .group_by(genres.c.id, genres.c.name)
        .order_by(func.lower(genres.c.name))
    ).all()


def track_ids_by_genre(conn: Connection, genre: str, count: int, offset: int, root_id: int | None = None) -> list[int]:
    genre_id = genre_id_by_name(conn, genre)
    if genre_id is None:
        return []
    stmt = (
        select(tracks.c.id)
        .join(track_genres, track_genres.c.track_id == tracks.c.id)
        .where(track_genres.c.genre_id == genre_id, tracks.c.missing_since.is_(None))
    )
    if root_id is not None:
        stmt = stmt.where(tracks.c.root_id == root_id)
    stmt = stmt.order_by(tracks.c.artist_id, tracks.c.album_id, tracks.c.disc_no, tracks.c.track_no, tracks.c.id)
    return [r[0] for r in conn.execute(stmt.limit(count).offset(offset))]


# --- popularity ----------------------------------------------------------------------------


def top_track_ids(conn: Connection, artist_id: int, count: int) -> list[int]:
    """The artist's most played tracks over all users; filled up with their other tracks
    (newest albums first) when there is not enough history."""
    plays = func.count(play_history.c.id)
    played = [
        r[0]
        for r in conn.execute(
            select(tracks.c.id)
            .join(track_artists, track_artists.c.track_id == tracks.c.id)
            .join(play_history, play_history.c.track_id == tracks.c.id)
            .where(track_artists.c.artist_id == artist_id, tracks.c.missing_since.is_(None))
            .group_by(tracks.c.id)
            .order_by(plays.desc(), tracks.c.id)
            .limit(count)
        )
    ]
    if len(played) >= count:
        return played
    rest = conn.execute(
        select(tracks.c.id)
        .join(track_artists, track_artists.c.track_id == tracks.c.id)
        .where(
            track_artists.c.artist_id == artist_id,
            tracks.c.missing_since.is_(None),
            tracks.c.id.not_in(played) if played else literal(True),
        )
        .order_by(tracks.c.year.desc(), tracks.c.album_id, tracks.c.disc_no, tracks.c.track_no, tracks.c.id)
        .limit(count - len(played))
    )
    return played + [r[0] for r in rest]


# --- full listings (search3 with an empty query) --------------------------------------------


def all_ids(conn: Connection, kind: str, count: int, offset: int, root_id: int | None = None) -> list[int]:
    """Every track/album/artist in a stable order, paged by offset. Apps sync the whole library
    this way; the partial indexes make large offsets an index-only skip."""
    if kind == "track":
        stmt = select(tracks.c.id).where(tracks.c.missing_since.is_(None)).order_by(tracks.c.title_sort, tracks.c.id)
        if root_id is not None:
            stmt = stmt.where(tracks.c.root_id == root_id)
    elif kind == "album":
        stmt = select(albums.c.id).where(albums.c.track_count > 0).order_by(albums.c.title_sort, albums.c.id)
        if root_id is not None:
            stmt = stmt.where(_album_in_root(root_id))
    else:
        stmt = select(artists.c.id).where(artists.c.album_count > 0).order_by(artists.c.name_sort, artists.c.id)
        if root_id is not None:
            stmt = stmt.where(_artist_in_root(root_id))
    return [r[0] for r in conn.execute(stmt.limit(count).offset(offset))]
