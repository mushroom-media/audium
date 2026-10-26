"""audium rows -> Subsonic objects (Child, AlbumID3, ArtistID3, Playlist), with the user's
favorites and play counts. Each function takes whole lists so extras cost one query per list."""

import os
from datetime import UTC, datetime

from sqlalchemy import Connection

from audium.api.subsonic import ids
from audium.services import catalog
from audium.services.streaming import content_type
from audium.services.users import User

# Codecs every common app plays as they are; everything else is sent transcoded to MP3.
DIRECT_CODECS = frozenset({"mp3", "flac", "vorbis", "opus", "aac", "alac", "pcm"})
TRANSCODE_SUFFIX, TRANSCODE_TYPE = "mp3", "audio/mpeg"


def iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _seconds(ms: int | None) -> int:
    return round((ms or 0) / 1000)


# --- songs ---------------------------------------------------------------------------------


def songs(conn: Connection, user: User, track_ids: list[int]) -> list[dict]:
    return song_objects(conn, user, catalog.songs(conn, track_ids))


def song_objects(conn: Connection, user: User, rows: list) -> list[dict]:
    track_ids = [r.id for r in rows]
    genres = catalog.track_genres_of(conn, track_ids)
    artists = catalog.track_artists_of(conn, track_ids)
    starred = catalog.favorite_times(conn, user.id, "track", track_ids)
    plays = catalog.play_stats(conn, user.id, track_ids)
    return [_child(r, genres.get(r.id, []), artists.get(r.id, []), starred.get(r.id), plays.get(r.id)) for r in rows]


def _child(r, genres: list[str], artists: list[tuple[int, str]], starred: int | None, plays) -> dict:
    suffix = os.path.splitext(r.rel_path)[1].lstrip(".").lower() or None
    count, last = plays or (0, None)
    replay_gain = _clean(
        {
            "trackGain": r.rg_track_gain,
            "trackPeak": r.rg_track_peak,
            "albumGain": r.rg_album_gain,
            "albumPeak": r.rg_album_peak,
        }
    )
    child = {
        "id": ids.make(ids.TRACK, r.id),
        "parent": ids.make(ids.ALBUM, r.album_id),
        "isDir": False,
        "title": r.title,
        "album": r.album_title,
        "artist": r.artist_name,
        "track": r.track_no,
        "discNumber": r.disc_no,
        "year": r.year or None,
        "genre": genres[0] if genres else None,
        "coverArt": ids.cover(r.cover),
        "size": r.size,
        "contentType": content_type(r.container),
        "suffix": suffix,
        "duration": _seconds(r.duration_ms),
        "bitRate": round(r.bitrate / 1000) if r.bitrate else None,
        "samplingRate": r.sample_rate,
        "bitDepth": r.bit_depth,
        "channelCount": r.channels,
        "path": r.rel_path,
        "isVideo": False,
        "playCount": count,
        "played": iso(last),
        "created": iso(r.added_at),
        "starred": iso(starred),
        "albumId": ids.make(ids.ALBUM, r.album_id),
        "artistId": ids.make(ids.ARTIST, r.artist_id),
        "type": "music",
        "mediaType": "song",
        "sortName": r.title_sort,
        "musicBrainzId": r.mb_recording_id,
        "genres": [{"name": g} for g in genres],
        "artists": [{"id": ids.make(ids.ARTIST, a), "name": n} for a, n in artists],
        "displayArtist": r.artist_name,
        "replayGain": replay_gain or None,
    }
    if r.codec not in DIRECT_CODECS:
        child["transcodedSuffix"] = TRANSCODE_SUFFIX
        child["transcodedContentType"] = TRANSCODE_TYPE
    return _clean(child)


# --- albums --------------------------------------------------------------------------------


def albums(conn: Connection, user: User, album_ids: list[int], as_dir: bool = False) -> list[dict]:
    return album_objects(conn, user, catalog.album_rows(conn, album_ids), as_dir)


def album_objects(conn: Connection, user: User, rows: list, as_dir: bool = False) -> list[dict]:
    """AlbumID3, or with `as_dir` the folder-style Child the non-ID3 endpoints use."""
    album_ids = [r.id for r in rows]
    genres = catalog.album_genres_of(conn, album_ids)
    starred = catalog.favorite_times(conn, user.id, "album", album_ids)
    plays = catalog.album_play_stats(conn, user.id, album_ids)
    out = []
    for r in rows:
        g = genres.get(r.id, [])
        count, last = plays.get(r.id) or (0, None)
        common = {
            "id": ids.make(ids.ALBUM, r.id),
            "artist": r.artist_name,
            "year": r.year or None,
            "genre": g[0] if g else None,
            "coverArt": ids.cover(r.cover),
            "created": iso(r.added_at),
            "starred": iso(starred.get(r.id)),
            "playCount": count,
            "played": iso(last),
        }
        if as_dir:
            item = {
                **common,
                "parent": ids.make(ids.ARTIST, r.album_artist_id),
                "isDir": True,
                "title": r.title,
                "album": r.title,
                "artistId": ids.make(ids.ARTIST, r.album_artist_id),
                "duration": _seconds(r.duration_ms),
            }
        else:
            item = {
                **common,
                "name": r.title,
                "artistId": ids.make(ids.ARTIST, r.album_artist_id),
                "songCount": r.track_count,
                "duration": _seconds(r.duration_ms),
                "isCompilation": bool(r.compilation),
                "sortName": r.title_sort,
                "musicBrainzId": r.mb_release_id,
                "genres": [{"name": x} for x in g],
                "artists": [{"id": ids.make(ids.ARTIST, r.album_artist_id), "name": r.artist_name}],
                "displayArtist": r.artist_name,
            }
        out.append(_clean(item))
    return out


# --- artists -------------------------------------------------------------------------------


def artists(conn: Connection, user: User, artist_ids: list[int]) -> list[dict]:
    return artist_objects(conn, user, catalog.artist_rows(conn, artist_ids))


def artist_objects(conn: Connection, user: User, rows: list) -> list[dict]:
    starred = catalog.favorite_times(conn, user.id, "artist", [r.id for r in rows])
    return [
        _clean(
            {
                "id": ids.make(ids.ARTIST, r.id),
                "name": r.name,
                # Artists without an own picture: getCoverArt answers with one of their albums.
                "coverArt": ids.cover(r.cover) or ids.make(ids.ARTIST, r.id),
                "albumCount": r.album_count,
                "starred": iso(starred.get(r.id)),
                "sortName": r.name_sort,
                "musicBrainzId": r.mb_artist_id,
            }
        )
        for r in rows
    ]


# --- playlists -----------------------------------------------------------------------------


def playlist(pl: dict, allowed_users: list[str] | None = None) -> dict:
    """From services.playlists.playlist_out. Smart playlists fill themselves and are read-only
    here; frozen auto-playlists are ordinary editable lists."""
    editable = pl["role"] in ("owner", "editor") and pl["kind"] != "smart"
    return _clean(
        {
            "id": ids.make(ids.PLAYLIST, pl["id"]),
            "name": pl["name"],
            "comment": pl["description"],
            "owner": pl["owner"]["username"],
            "public": pl["visibility"] == "users",
            "songCount": pl["item_count"],
            "duration": _seconds(pl["duration_ms"]),
            "created": iso(pl["created_at"]),
            "changed": iso(pl["updated_at"]),
            "coverArt": ids.cover(pl["cover"]) or ids.make(ids.PLAYLIST, pl["id"]),
            "readonly": not editable,
            "allowedUser": allowed_users,
        }
    )


AUTO_OWNER = "audium"


def auto_playlist(auto: dict) -> dict:
    """From services.auto.get_auto: generated by audium, never editable through Subsonic."""
    return _clean(
        {
            "id": ids.make(ids.AUTO, auto["id"]),
            "name": auto["name"],
            "comment": auto["description"],
            "owner": AUTO_OWNER,
            "public": True,
            "songCount": auto["track_count"],
            "duration": _seconds(auto["duration_ms"]),
            "created": iso(auto["generated_at"]),
            "changed": iso(auto["generated_at"]),
            "coverArt": ids.cover(auto["cover"]) or ids.make(ids.AUTO, auto["id"]),
            "readonly": True,
        }
    )
