"""Album and song lists: getAlbumList(2), random songs, favorites, genres, top and similar
songs, what is playing now."""

import numpy as np

from audium.analysis.similarity import group_radio, radio
from audium.api.subsonic import ids, mapping
from audium.api.subsonic.envelope import GENERIC, NOT_FOUND, SubsonicError
from audium.api.subsonic.routing import Call, endpoint
from audium.services import catalog, personal
from audium.util import now_ms

MAX_LIST = 500


def _album_ids(call: Call, conn) -> list[int]:
    kind = call.require("type")
    if kind not in catalog.ALBUM_LIST_TYPES:
        raise SubsonicError(GENERIC, f"unknown list type: {kind}")
    if kind == "byGenre":
        call.require("genre")
    if kind == "byYear":
        call.require("fromYear")
        call.require("toYear")
    return catalog.album_list(
        conn,
        call.user.id,
        kind,
        call.int("size", 10, 1, MAX_LIST),
        call.int("offset", 0, 0),
        from_year=call.int("fromYear"),
        to_year=call.int("toYear"),
        genre=call.get("genre"),
        root_id=ids.folder(call.get("musicFolderId")),
    )


@endpoint("getAlbumList2")
def get_album_list2(call: Call) -> dict:
    with call.db.read() as conn:
        albums = mapping.albums(conn, call.user, _album_ids(call, conn))
    return {"albumList2": {"album": albums}}


@endpoint("getAlbumList")
def get_album_list(call: Call) -> dict:
    with call.db.read() as conn:
        albums = mapping.albums(conn, call.user, _album_ids(call, conn), as_dir=True)
    return {"albumList": {"album": albums}}


@endpoint("getRandomSongs")
def get_random_songs(call: Call) -> dict:
    with call.db.read() as conn:
        track_ids = catalog.random_track_ids(
            conn,
            call.int("size", 10, 1, MAX_LIST),
            genre=call.get("genre") or None,
            from_year=call.int("fromYear"),
            to_year=call.int("toYear"),
            root_id=ids.folder(call.get("musicFolderId")),
        )
        songs = mapping.songs(conn, call.user, track_ids)
    return {"randomSongs": {"song": songs}}


@endpoint("getSongsByGenre")
def get_songs_by_genre(call: Call) -> dict:
    with call.db.read() as conn:
        track_ids = catalog.track_ids_by_genre(
            conn,
            call.require("genre"),
            call.int("count", 10, 1, MAX_LIST),
            call.int("offset", 0, 0),
            ids.folder(call.get("musicFolderId")),
        )
        songs = mapping.songs(conn, call.user, track_ids)
    return {"songsByGenre": {"song": songs}}


def _starred(call: Call, as_dir: bool) -> dict:
    user = call.user
    with call.db.read() as conn:
        artist_ids = personal.favorite_ids(conn, user.id, "artist")
        album_ids = personal.favorite_ids(conn, user.id, "album")
        track_ids = personal.favorite_ids(conn, user.id, "track")
        return {
            "artist": mapping.artists(conn, user, artist_ids),
            "album": mapping.albums(conn, user, album_ids, as_dir=as_dir),
            "song": mapping.songs(conn, user, track_ids),
        }


@endpoint("getStarred2")
def get_starred2(call: Call) -> dict:
    return {"starred2": _starred(call, as_dir=False)}


@endpoint("getStarred")
def get_starred(call: Call) -> dict:
    return {"starred": _starred(call, as_dir=True)}


@endpoint("getNowPlaying")
def get_now_playing(call: Call) -> dict:
    """Only the caller's own entries: other users do not see what someone listens to."""
    entries = call.state.now_playing.for_user(call.user.id)
    with call.db.read() as conn:
        songs = {s["id"]: s for s in mapping.songs(conn, call.user, [e.track_id for e in entries])}
    now = now_ms()
    out = []
    for e in entries:
        song = songs.get(ids.make(ids.TRACK, e.track_id))
        if song is None:
            continue
        out.append(
            {
                **song,
                "username": call.user.username,
                "minutesAgo": (now - e.started_at) // 60_000,
                "playerId": 0,
                **({"playerName": e.client} if e.client else {}),
            }
        )
    return {"nowPlaying": {"entry": out}}


@endpoint("getTopSongs")
def get_top_songs(call: Call) -> dict:
    name = call.require("artist")
    count = call.int("count", 50, 1, MAX_LIST)
    with call.db.read() as conn:
        artist = catalog.find_artist_by_name(conn, name)
        songs = mapping.songs(conn, call.user, catalog.top_track_ids(conn, artist.id, count)) if artist else []
    return {"topSongs": {"song": songs}}


def _similar(call: Call, key: str) -> dict:
    """A radio station (docs: Discover/Radio) from a track, album or artist."""
    kind, item_id = ids.parse(call.require("id"), ids.TRACK, ids.ALBUM, ids.ARTIST)
    count = call.int("count", 50, 1, MAX_LIST)
    rng = np.random.default_rng()
    vectors = call.state.vectors
    with call.db.read() as conn:
        if kind == ids.TRACK:
            if not catalog.songs(conn, [item_id]):
                raise SubsonicError(NOT_FOUND, "song not found")
            # Subsonic leaves the seed out: the app already plays it.
            track_ids = radio(conn, vectors, item_id, count + 1, rng)[1:]
        else:
            members = (
                catalog.album_track_ids(conn, item_id) if kind == ids.ALBUM else catalog.artist_track_ids(conn, item_id)
            )
            if not members:
                raise SubsonicError(NOT_FOUND, "not found")
            track_ids = group_radio(conn, vectors, members, count, rng)
        songs = mapping.songs(conn, call.user, track_ids)
    return {key: {"song": songs}}


@endpoint("getSimilarSongs")
def get_similar_songs(call: Call) -> dict:
    return _similar(call, "similarSongs")


@endpoint("getSimilarSongs2")
def get_similar_songs2(call: Call) -> dict:
    return _similar(call, "similarSongs2")
