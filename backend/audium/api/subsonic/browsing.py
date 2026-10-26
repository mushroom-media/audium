"""Browsing by tags (ID3 endpoints) and the virtual folder view of older apps."""

import os

from audium.analysis.similarity import fallback_group
from audium.api.subsonic import ids, mapping
from audium.api.subsonic.envelope import NOT_FOUND, SubsonicError
from audium.api.subsonic.routing import Call, endpoint
from audium.services import catalog


def _letter(name_sort: str) -> str:
    ch = (name_sort or "#")[:1].upper()
    return ch if "A" <= ch <= "Z" else "#"


def _index(call: Call, conn, root_id: int | None) -> list[dict]:
    """Album artists grouped by initial, as getArtists and getIndexes expect."""
    rows = catalog.album_artists(conn, root_id)
    objects = mapping.artist_objects(conn, call.user, rows)
    groups: dict[str, list[dict]] = {}
    for row, obj in zip(rows, objects, strict=True):
        groups.setdefault(_letter(row.name_sort), []).append(obj)
    order = sorted(groups, key=lambda k: (k == "#", k))
    return [{"name": k, "artist": groups[k]} for k in order]


@endpoint("getMusicFolders")
def get_music_folders(call: Call) -> dict:
    with call.db.read() as conn:
        rows = catalog.music_folders(conn)
    folders = [{"id": r.id, "name": os.path.basename(r.path.rstrip("/\\")) or r.path} for r in rows]
    return {"musicFolders": {"musicFolder": folders}}


@endpoint("getArtists")
def get_artists(call: Call) -> dict:
    root_id = ids.folder(call.get("musicFolderId"))
    with call.db.read() as conn:
        index = _index(call, conn, root_id)
    return {"artists": {"ignoredArticles": call.settings.ignored_articles, "index": index}}


@endpoint("getIndexes")
def get_indexes(call: Call) -> dict:
    root_id = ids.folder(call.get("musicFolderId"))
    since = call.int("ifModifiedSince", 0)
    with call.db.read() as conn:
        modified = catalog.last_modified(conn)
        index = _index(call, conn, root_id) if not since or modified > since else []
    return {"indexes": {"lastModified": modified, "ignoredArticles": call.settings.ignored_articles, "index": index}}


@endpoint("getArtist")
def get_artist(call: Call) -> dict:
    artist_id = ids.parse_one(call.require("id"), ids.ARTIST)
    with call.db.read() as conn:
        found = mapping.artists(conn, call.user, [artist_id])
        if not found:
            raise SubsonicError(NOT_FOUND, "artist not found")
        albums = mapping.album_objects(conn, call.user, catalog.albums_of_artist(conn, artist_id))
    return {"artist": {**found[0], "album": albums}}


@endpoint("getAlbum")
def get_album(call: Call) -> dict:
    album_id = ids.parse_one(call.require("id"), ids.ALBUM)
    with call.db.read() as conn:
        found = mapping.albums(conn, call.user, [album_id])
        if not found:
            raise SubsonicError(NOT_FOUND, "album not found")
        songs = mapping.songs(conn, call.user, catalog.album_track_ids(conn, album_id))
    return {"album": {**found[0], "song": songs}}


@endpoint("getSong")
def get_song(call: Call) -> dict:
    track_id = ids.parse_one(call.require("id"), ids.TRACK)
    with call.db.read() as conn:
        found = mapping.songs(conn, call.user, [track_id])
    if not found:
        raise SubsonicError(NOT_FOUND, "song not found")
    return {"song": found[0]}


@endpoint("getMusicDirectory")
def get_music_directory(call: Call) -> dict:
    """Folders are virtual: artist -> albums -> tracks, the same structure as getIndexes."""
    kind, item_id = ids.parse(call.require("id"), ids.ARTIST, ids.ALBUM)
    with call.db.read() as conn:
        if kind == ids.ARTIST:
            artist = mapping.artists(conn, call.user, [item_id])
            if not artist:
                raise SubsonicError(NOT_FOUND, "artist not found")
            children = mapping.album_objects(conn, call.user, catalog.albums_of_artist(conn, item_id), as_dir=True)
            directory = {"id": artist[0]["id"], "name": artist[0]["name"], "starred": artist[0].get("starred")}
        else:
            album = mapping.albums(conn, call.user, [item_id])
            if not album:
                raise SubsonicError(NOT_FOUND, "album not found")
            children = mapping.songs(conn, call.user, catalog.album_track_ids(conn, item_id))
            directory = {
                "id": album[0]["id"],
                "parent": album[0]["artistId"],
                "name": album[0]["name"],
                "starred": album[0].get("starred"),
            }
    return {"directory": {**{k: v for k, v in directory.items() if v is not None}, "child": children}}


@endpoint("getGenres")
def get_genres(call: Call) -> dict:
    with call.db.read() as conn:
        rows = catalog.genre_counts(conn)
    return {"genres": {"genre": [{"value": r.name, "songCount": r.songs, "albumCount": r.albums} for r in rows]}}


@endpoint("getAlbumInfo")
@endpoint("getAlbumInfo2")
def get_album_info(call: Call) -> dict:
    album_id = ids.parse_one(call.require("id"), ids.ALBUM)
    with call.db.read() as conn:
        rows = catalog.album_rows(conn, [album_id])
    if not rows:
        raise SubsonicError(NOT_FOUND, "album not found")
    info = {"notes": "", "musicBrainzId": rows[0].mb_release_id}
    return {"albumInfo": {k: v for k, v in info.items() if v is not None}}


@endpoint("getArtistInfo2")
def get_artist_info(call: Call) -> dict:
    artist_id = ids.parse_one(call.require("id"), ids.ARTIST)
    count = call.int("count", 20, 0, 100)
    with call.db.read() as conn:
        rows = catalog.artist_rows(conn, [artist_id])
        if not rows:
            raise SubsonicError(NOT_FOUND, "artist not found")
        similar_ids = _similar_artists(call, conn, artist_id, count) if count else []
        similar = mapping.artist_objects(conn, call.user, catalog.artist_rows(conn, similar_ids))
    info = {"biography": "", "musicBrainzId": rows[0].mb_artist_id, "similarArtist": similar}
    return {"artistInfo2": {k: v for k, v in info.items() if v is not None}}


def _similar_artists(call: Call, conn, artist_id: int, count: int) -> list[int]:
    """Album artists of the tracks that sound most like this artist (or share their genres)."""
    own = catalog.artist_track_ids(conn, artist_id, limit=500)
    if not own:
        return []
    near = call.state.vectors.nearest_to_group(conn, own, 300)
    candidates = [t for t, _ in near] if near else fallback_group(conn, own, 300)
    album_artist = catalog.album_artist_of(conn, candidates)
    out: list[int] = []
    for t in candidates:
        a = album_artist.get(t)
        if a is not None and a != artist_id and a not in out:
            out.append(a)
            if len(out) >= count:
                break
    return out
