"""Radio stations suggested on the home page, from the user's own listening.

Each suggestion is a station the radio endpoints already know (an artist, album or track) plus a
short reason. The picks:

- artists played a lot lately (plays weighted by how recent they are),
- the album played most lately, if its artist is not picked already,
- artists played a lot before but not for a while ("Länger nicht gehört"),
- recently favorited tracks.

Which of the strong candidates make it changes once a day (seeded per user and day), so the
row does not look the same every visit, but stays put within a day. That makes it safe to keep the
result (SuggestionCache): working it out reads 10,000 history entries on every visit of the home page.
"""

import math
import random
import threading
import time
from collections import defaultdict

from sqlalchemy import Connection, func, select

from audium.db.pagination import fetch_ordered
from audium.db.schema import albums, artists, favorites, play_history, tracks
from audium.db.state import LIBRARY_GENERATION, get_state
from audium.services.library import album_select, artist_select, track_select
from audium.services.users import User
from audium.util import now_ms

DAY_MS = 86_400_000
RECENT_DAYS = 30  # "lately"
HALF_LIFE_DAYS = 10  # a play counts half as much after this many days
REDISCOVER_MIN_PLAYS = 4  # plays before the recent window that make an artist "known"
MIN_RECENT_PLAYS = 2
SCAN = 10_000  # history entries looked at (the history keeps this many per user)
# Slots per kind; leftovers go to more artists played lately.
SLOTS = {"recent": 3, "album": 1, "rediscover": 2, "favorite": 2}
_CACHE_FULL_S = 3600
_CACHE_SHORT_S = 60
_CACHE_ENTRIES = 256


def _weighted_pick(rng: random.Random, scored: list[tuple[int, float]], k: int) -> list[int]:
    """Up to `k` ids, the higher the score the likelier (no repeats)."""
    pool = list(scored)
    out = []
    while pool and len(out) < k:
        total = sum(s for _, s in pool)
        x = rng.random() * total
        for i, (item, s) in enumerate(pool):
            x -= s
            if x <= 0 or i == len(pool) - 1:
                out.append(item)
                pool.pop(i)
                break
    return out


def suggestions(conn: Connection, user: User, limit: int = 8, now: int | None = None) -> list[dict]:
    now = now or now_ms()
    rows = conn.execute(
        select(play_history.c.played_at, tracks.c.artist_id, tracks.c.album_id)
        .join(tracks, tracks.c.id == play_history.c.track_id)
        .where(play_history.c.user_id == user.id, tracks.c.missing_since.is_(None))
        .order_by(play_history.c.played_at.desc())
        .limit(SCAN)
    ).all()
    recent_from = now - RECENT_DAYS * DAY_MS
    artist_score: dict[int, float] = defaultdict(float)
    artist_recent: dict[int, int] = defaultdict(int)
    artist_before: dict[int, int] = defaultdict(int)
    album_score: dict[int, float] = defaultdict(float)
    album_recent: dict[int, int] = defaultdict(int)
    album_artist: dict[int, int | None] = {}
    for r in rows:
        if r.played_at >= recent_from:
            weight = 0.5 ** ((now - r.played_at) / (HALF_LIFE_DAYS * DAY_MS))
            if r.artist_id is not None:
                artist_score[r.artist_id] += weight
                artist_recent[r.artist_id] += 1
            album_score[r.album_id] += weight
            album_recent[r.album_id] += 1
            album_artist[r.album_id] = r.artist_id
        elif r.artist_id is not None:
            artist_before[r.artist_id] += 1

    rng = random.Random(f"{user.id}:{time.strftime('%Y-%m-%d', time.gmtime(now / 1000))}")
    picked: list[tuple[str, int, str]] = []  # (kind, id, reason)
    used_artists: set[int] = set()

    def add_artists(candidates: list[tuple[int, float]], k: int, reason: str) -> None:
        for artist_id in _weighted_pick(rng, [c for c in candidates if c[0] not in used_artists], k):
            used_artists.add(artist_id)
            picked.append(("artist", artist_id, reason))

    lately = sorted(
        ((a, s) for a, s in artist_score.items() if artist_recent[a] >= MIN_RECENT_PLAYS),
        key=lambda c: -c[1],
    )
    add_artists(lately[:8], SLOTS["recent"], "Oft gehört")

    for album_id, _ in sorted(album_score.items(), key=lambda c: -c[1]):
        if album_recent[album_id] >= MIN_RECENT_PLAYS and album_artist.get(album_id) not in used_artists:
            picked.append(("album", album_id, "Gerade viel gehört"))
            if album_artist.get(album_id) is not None:
                used_artists.add(album_artist[album_id])
            break

    forgotten = [
        (a, math.log1p(n)) for a, n in artist_before.items() if n >= REDISCOVER_MIN_PLAYS and a not in artist_recent
    ]
    forgotten.sort(key=lambda c: -c[1])
    add_artists(forgotten[:10], SLOTS["rediscover"], "Länger nicht gehört")

    faves = conn.execute(
        select(favorites.c.item_id, tracks.c.artist_id)
        .join(tracks, tracks.c.id == favorites.c.item_id)
        .where(
            favorites.c.user_id == user.id,
            favorites.c.item_type == "track",
            tracks.c.missing_since.is_(None),
        )
        .order_by(favorites.c.created_at.desc())
        .limit(20)
    ).all()
    fresh = [(f.item_id, 1.0 / (i + 1)) for i, f in enumerate(faves) if f.artist_id not in used_artists]
    fave_artist = {f.item_id: f.artist_id for f in faves}
    for track_id in _weighted_pick(rng, fresh, SLOTS["favorite"]):
        picked.append(("track", track_id, "Aus deinen Lieblingssongs"))
        used_artists.add(fave_artist[track_id])

    add_artists(lately[8:] + lately[:8], limit - len(picked), "Oft gehört")
    return _describe(conn, picked[:limit])


class SuggestionCache:
    """Keeps a user's suggestions for the day, at most an hour. A row that is not full yet (someone
    who just started listening) follows every new play, so it fills up while they listen. A library
    change starts over, because the picks may be gone."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[tuple, tuple[float, int | None, list[dict]]] = {}

    def get(self, conn: Connection, user: User, limit: int) -> list[dict]:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        key = (user.id, limit, day, get_state(conn, LIBRARY_GENERATION))
        last_play = conn.execute(
            select(func.max(play_history.c.played_at)).where(play_history.c.user_id == user.id)
        ).scalar()
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
        if hit and now < hit[0] and (len(hit[2]) >= limit or hit[1] == last_play):
            return hit[2]
        result = suggestions(conn, user, limit)
        ttl = _CACHE_FULL_S if len(result) >= limit else _CACHE_SHORT_S
        with self._lock:
            if len(self._data) >= _CACHE_ENTRIES:
                self._data.clear()
            self._data[key] = (now + ttl, last_play, result)
        return result


def _describe(conn: Connection, picked: list[tuple[str, int, str]]) -> list[dict]:
    """The picks as "recently played" style entries (RecentOut), dropping ones that are gone."""
    by_kind: dict[str, list[int]] = defaultdict(list)
    for kind, item_id, _ in picked:
        by_kind[kind].append(item_id)
    found = {
        "artist": {
            r.id: (r.name, r.fallback_cover)  # a station always gets a picture, whatever the artist setting
            for r in fetch_ordered(conn, artist_select(), artists.c.id, by_kind["artist"])
        },
        "album": {r.id: (r.title, r.cover) for r in fetch_ordered(conn, album_select(), albums.c.id, by_kind["album"])},
        "track": {r.id: (r.title, r.cover) for r in fetch_ordered(conn, track_select(), tracks.c.id, by_kind["track"])},
    }
    out = []
    for kind, item_id, reason in picked:
        if item_id not in found[kind]:
            continue
        name, cover = found[kind][item_id]
        out.append(
            {
                "type": "radio",
                "id": item_id,
                "radio_of": kind,
                "name": name,
                "subtitle": reason,
                "cover": cover,
                "cover_preset": None,
            }
        )
    return out
