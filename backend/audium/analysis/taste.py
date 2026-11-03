"""A user's own taste in their stations: what they like moves up, what they skipped moves down.

- Taste (radio source "taste", analysis/sources.py): of the tracks the other sources found, those
  the user marked as favourite (the track, its album or its artist) or played often rank higher.
  It never brings in tracks of its own, so a station stays about its seed.
- Skips (always on, radios only): a track skipped within the first SKIP_S seconds of a radio
  counts against it in later stations that are like that one: the same seed fully, a seed by
  the same artist less, a seed by an artist ListenBrainz calls similar (artist_similar) a little.
  Shuffle, playlists and "similar tracks" are not affected. Old skips fade (SKIP_HALF_LIFE_DAYS)
  and are forgotten after SKIP_KEEP_DAYS.
- Dislikes ("Mag ich nicht" in a radio's list): count like a skip, and the track doesn't come up
  in that same station at all, until forgotten like a skip.
"""

import math
import re

from sqlalchemy import Connection, delete, func, insert, or_, select

from audium.db.schema import albums, artist_similar, favorites, play_history, radio_skips, track_artists, tracks
from audium.util import now_ms

_DAY_MS = 86_400_000
SKIP_S = 30  # a radio track skipped before this counts as not wanted (the client decides)
SKIP_KEEP_DAYS = 180
SKIP_HALF_LIFE_DAYS = 60
# How much a skip counts in another station, by how alike the two stations are.
SAME_STATION = 1.0
SAME_ARTIST = 0.6
SIMILAR_ARTIST = 0.4  # x the ListenBrainz score
# A track's score is divided by (1 + SKIP_WEIGHT x its skips), so one skip in the same station
# leaves a third, one in a station of the same artist a bit under half.
SKIP_WEIGHT = 2.0

# What a station is: "track:3", "album:5", "artist:2".
_STATION = re.compile(r"^(track|album|artist):(\d+)$")

# Affinity: a favourite track counts most, a favourite album or artist less, plays add up slowly.
_FAV_TRACK = 3.0
_FAV_GROUP = 1.5
_PLAYS_CAP = 3.0


def affinity(conn: Connection, user_id: int, track_ids: list[int]) -> dict[int, float]:
    """track -> how much the user likes it (> 0), for those of `track_ids` they like at all."""
    if not track_ids:
        return {}
    info = {r.id: r for r in conn.execute(select(tracks.c.id, tracks.c.album_id).where(tracks.c.id.in_(track_ids)))}
    artists_of: dict[int, set[int]] = {}
    for t, a in conn.execute(
        select(track_artists.c.track_id, track_artists.c.artist_id).where(track_artists.c.track_id.in_(track_ids))
    ):
        artists_of.setdefault(t, set()).add(a)
    favs: dict[str, set[int]] = {"track": set(), "album": set(), "artist": set()}
    for kind, item in conn.execute(
        select(favorites.c.item_type, favorites.c.item_id).where(favorites.c.user_id == user_id)
    ):
        favs.setdefault(kind, set()).add(item)
    plays = dict(
        conn.execute(
            select(play_history.c.track_id, func.count())
            .where(play_history.c.user_id == user_id, play_history.c.track_id.in_(track_ids))
            .group_by(play_history.c.track_id)
        ).all()
    )
    out: dict[int, float] = {}
    for t in track_ids:
        score = 0.0
        if t in favs["track"]:
            score += _FAV_TRACK
        if t in info and info[t].album_id in favs["album"]:
            score += _FAV_GROUP
        if artists_of.get(t, set()) & favs["artist"]:
            score += _FAV_GROUP
        if plays.get(t):
            score += min(_PLAYS_CAP, math.log2(1 + plays[t]))
        if score > 0:
            out[t] = score
    return out


def taste_list(conn: Connection, user_id: int, candidates: list[int]) -> list[int]:
    """The candidates the user likes, the most liked first."""
    liked = affinity(conn, user_id, candidates)
    return sorted(liked, key=lambda t: -liked[t])


# --- skips -----------------------------------------------------------------------------------


def parse_station(station: str | None) -> tuple[str, int] | None:
    m = _STATION.match(station or "")
    return (m[1], int(m[2])) if m else None


def record_skip(conn: Connection, user_id: int, track_id: int, station: str, disliked: bool = False) -> bool:
    """Store a skip or dislike; False when it does not count (unknown station, or its own seed track)."""
    parsed = parse_station(station)
    if parsed is None or parsed == ("track", track_id):
        return False
    if conn.execute(select(tracks.c.id).where(tracks.c.id == track_id)).first() is None:
        return False
    conn.execute(
        insert(radio_skips).values(
            user_id=user_id, track_id=track_id, station=station, skipped_at=now_ms(), disliked=disliked
        )
    )
    return True


def dislikes(conn: Connection, user_id: int, station: str | None) -> set[int]:
    """The tracks the user doesn't want in this station."""
    if parse_station(station) is None:
        return set()
    return set(
        conn.execute(
            select(radio_skips.c.track_id).where(
                radio_skips.c.user_id == user_id,
                radio_skips.c.station == station,
                radio_skips.c.disliked,
                radio_skips.c.skipped_at >= now_ms() - SKIP_KEEP_DAYS * _DAY_MS,
            )
        ).scalars()
    )


def prune_skips(conn: Connection) -> None:
    conn.execute(delete(radio_skips).where(radio_skips.c.skipped_at < now_ms() - SKIP_KEEP_DAYS * _DAY_MS))


def _seed_artists(conn: Connection, stations: set[tuple[str, int]]) -> dict[tuple[str, int], set[int]]:
    """station -> the artists it is about: a track's main artists, an album's album artist and
    main artists, or the artist itself."""
    out: dict[tuple[str, int], set[int]] = {s: set() for s in stations}
    track_seeds = [i for k, i in stations if k == "track"]
    album_seeds = [i for k, i in stations if k == "album"]
    for k, i in stations:
        if k == "artist":
            out[(k, i)].add(i)
    if track_seeds:
        for t, a in conn.execute(
            select(track_artists.c.track_id, track_artists.c.artist_id).where(
                track_artists.c.track_id.in_(track_seeds), track_artists.c.role == "main"
            )
        ):
            out[("track", t)].add(a)
    if album_seeds:
        for album_id, a in conn.execute(
            select(albums.c.id, albums.c.album_artist_id).where(albums.c.id.in_(album_seeds))
        ):
            out[("album", album_id)].add(a)
        for album_id, a in conn.execute(
            select(tracks.c.album_id, track_artists.c.artist_id)
            .join(track_artists, track_artists.c.track_id == tracks.c.id)
            .where(tracks.c.album_id.in_(album_seeds), track_artists.c.role == "main")
            .distinct()
        ):
            out[("album", album_id)].add(a)
    return out


def skip_penalties(conn: Connection, user_id: int, station: str | None, track_ids: list[int]) -> dict[int, float]:
    """track -> the factor (0..1) its score is multiplied with in this station, for tracks the
    user skipped in this or a similar station."""
    here = parse_station(station)
    if here is None or not track_ids:
        return {}
    now = now_ms()
    rows = conn.execute(
        select(radio_skips.c.track_id, radio_skips.c.station, radio_skips.c.skipped_at).where(
            radio_skips.c.user_id == user_id,
            radio_skips.c.track_id.in_(track_ids),
            radio_skips.c.skipped_at >= now - SKIP_KEEP_DAYS * _DAY_MS,
        )
    ).all()
    if not rows:
        return {}
    parsed = {r.station: parse_station(r.station) for r in rows}
    stations = {p for p in parsed.values() if p} | {here}
    artists_of = _seed_artists(conn, stations)
    mine = artists_of[here]
    # ListenBrainz: how close each other station's artists are to this one's (either direction).
    others = set().union(*(artists_of[s] for s in stations if s != here)) - mine
    close: dict[int, float] = {}
    if mine and others:
        for a, b, score in conn.execute(
            select(artist_similar.c.artist_id, artist_similar.c.similar_id, artist_similar.c.score).where(
                or_(
                    artist_similar.c.artist_id.in_(mine) & artist_similar.c.similar_id.in_(others),
                    artist_similar.c.artist_id.in_(others) & artist_similar.c.similar_id.in_(mine),
                )
            )
        ):
            other = b if a in mine else a
            close[other] = max(close.get(other, 0.0), score)

    def alike(s: tuple[str, int]) -> float:
        if s == here:
            return SAME_STATION
        theirs = artists_of.get(s, set())
        if theirs & mine:
            return SAME_ARTIST
        return SIMILAR_ARTIST * max((close.get(a, 0.0) for a in theirs), default=0.0)

    weight: dict[int, float] = {}
    for r in rows:
        s = parsed[r.station]
        if s is None:
            continue
        age_days = max(0, now - r.skipped_at) / _DAY_MS
        w = alike(s) * 0.5 ** (age_days / SKIP_HALF_LIFE_DAYS)
        if w > 0:
            weight[r.track_id] = weight.get(r.track_id, 0.0) + w
    return {t: 1.0 / (1.0 + SKIP_WEIGHT * w) for t, w in weight.items() if w >= 0.05}
