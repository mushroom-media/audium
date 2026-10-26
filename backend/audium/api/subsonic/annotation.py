"""Favorites (star/unstar), plays (scrobble) and ratings. All of it is the same per-user data
the web UI shows: a song starred in an app is a favorite in the browser, and vice versa."""

from audium.api.subsonic import ids
from audium.api.subsonic.envelope import GENERIC, SubsonicError
from audium.api.subsonic.routing import Call, endpoint
from audium.services import catalog, personal

_TYPES = {ids.TRACK: "track", ids.ALBUM: "album", ids.ARTIST: "artist"}


def _targets(call: Call) -> list[tuple[str, int]]:
    """`id` may name a song, album or artist (folder-style apps star albums by id);
    `albumId` and `artistId` name albums and artists."""
    out = [ids.parse(v, ids.TRACK, ids.ALBUM, ids.ARTIST) for v in call.getall("id")]
    out += [(ids.ALBUM, ids.parse_one(v, ids.ALBUM)) for v in call.getall("albumId")]
    out += [(ids.ARTIST, ids.parse_one(v, ids.ARTIST)) for v in call.getall("artistId")]
    return [(_TYPES[kind], item_id) for kind, item_id in out]  # type: ignore[misc]


def _set(call: Call, on: bool) -> dict:
    targets = _targets(call)
    with call.db.write() as conn:
        for item_type, item_id in targets:
            personal.set_favorite(conn, call.user.id, item_type, item_id, on)
    return {}


@endpoint("star")
def star(call: Call) -> dict:
    return _set(call, True)


@endpoint("unstar")
def unstar(call: Call) -> dict:
    return _set(call, False)


@endpoint("scrobble")
def scrobble(call: Call) -> dict:
    """submission=true (default): the song was played, it goes into the history (with the app's
    name and, for plays reported later, their time). false: it is playing now."""
    track_ids = [ids.parse_one(v, ids.TRACK) for v in call.getall("id")]
    if not track_ids:
        call.require("id")
    times = [int(t) for t in call.getall("time") if t.strip().isdigit()]
    submission = call.bool("submission", True)
    with call.db.read() as conn:
        durations = {r.id: r.duration_ms for r in catalog.songs(conn, track_ids)}
    if not submission:
        for track_id in track_ids:
            if track_id in durations:
                call.state.now_playing.report(call.user.id, track_id, durations[track_id], call.client)
        return {}
    with call.db.write() as conn:
        for i, track_id in enumerate(track_ids):
            if track_id not in durations:
                continue  # a song that is gone meanwhile: nothing to record, no reason to fail
            personal.record_play(
                conn,
                call.user.id,
                track_id,
                durations[track_id],
                client=call.client,
                played_at=times[i] if i < len(times) else None,
            )
    return {}


@endpoint("setRating")
def set_rating(call: Call) -> dict:
    raise SubsonicError(GENERIC, "audium has no ratings; use star/unstar for favorites")
