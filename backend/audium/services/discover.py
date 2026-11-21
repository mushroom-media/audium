"""The Discover page: the broad genres with their genres, and "Wieder reinhören" (albums and
artists you used to play a lot and have not for a while)."""

import math
import random
import time
from collections import Counter, defaultdict

from sqlalchemy import Connection, func, select

from audium.analysis import genres as genre_norm
from audium.db.pagination import fetch_ordered
from audium.db.schema import albums, artists, genres, play_history, track_genres, tracks
from audium.services import auto as auto_service
from audium.services.library import album_select, artist_select
from audium.services.users import User
from audium.util import now_ms

DAY_MS = 86_400_000
GENRE_PLAYS_DAYS = 90  # the broad genres you play most come first
REDISCOVER_AFTER_DAYS = 60  # not played for at least this long
REDISCOVER_MIN_PLAYS = 5  # plays before that make it "used to play a lot"
REDISCOVER_POOL = 24  # the best candidates; a few of them are picked per day
SCAN = 10_000  # history entries looked at (the history keeps this many per user)


def genre_overview(conn: Connection, user: User) -> dict:
    """The broad genres (family playlists) with the genre playlists inside, the ones you play
    most first, then by size; genre playlists without a family (or whose family the admin hid)
    under "others"."""
    visible = [
        a
        for a in auto_service.list_auto(conn, user)
        if a.get("status", "published") == "published" and a["key"].startswith(("family:", "genre:"))
    ]
    # A genre playlist may gather smaller genres under a genre nobody tagged ("Rock" from
    # "Krautrock" and "Classic Rock"): those are canonical names.
    family_of_slug = {genre_norm.slug(n): genre_norm.family(n) for n in genre_norm.CANONICAL}
    family_of_slug |= {r.slug: genre_norm.family(r.name) for r in conn.execute(select(genres.c.slug, genres.c.name))}
    family_by_slug = {genre_norm.slug(f): f for f in genre_norm.FAMILIES}

    since = now_ms() - GENRE_PLAYS_DAYS * DAY_MS
    plays: Counter[str] = Counter()
    for name, n in conn.execute(
        select(genres.c.name, func.count())
        .select_from(
            play_history.join(track_genres, track_genres.c.track_id == play_history.c.track_id).join(
                genres, genres.c.id == track_genres.c.genre_id
            )
        )
        .where(play_history.c.user_id == user.id, play_history.c.played_at >= since)
        .group_by(genres.c.name)
    ):
        fam = genre_norm.family(name)
        if fam:
            plays[fam] += n

    families: dict[str, dict] = {}
    for a in visible:
        if a["key"].startswith("family:") and (fam := family_by_slug.get(a["key"].removeprefix("family:"))):
            families[fam] = {"name": fam, "playlist": a, "genres": [], "plays": plays[fam]}
    others = []
    for a in visible:
        if not a["key"].startswith("genre:"):
            continue
        fam = family_of_slug.get(a["key"].removeprefix("genre:"))
        if fam in families:
            families[fam]["genres"].append(a)
        else:
            others.append(a)
    for f in families.values():
        f["genres"].sort(key=lambda a: -a["track_count"])
    ordered = sorted(families.values(), key=lambda f: (-f["plays"], -f["playlist"]["track_count"]))
    others.sort(key=lambda a: -a["track_count"])
    return {"families": ordered, "others": others}


def rediscover(conn: Connection, user: User, limit: int = 8, now: int | None = None) -> list[dict]:
    """Albums and artists you played at least REDISCOVER_MIN_PLAYS times, but not in the last
    REDISCOVER_AFTER_DAYS days. A day's pick from the strongest candidates (it changes daily);
    an artist does not come twice (as itself and with an album)."""
    now = now or now_ms()
    rows = conn.execute(
        select(play_history.c.played_at, tracks.c.album_id, tracks.c.artist_id, albums.c.album_artist_id)
        .join(tracks, tracks.c.id == play_history.c.track_id)
        .join(albums, albums.c.id == tracks.c.album_id)
        .where(play_history.c.user_id == user.id, tracks.c.missing_since.is_(None))
        .order_by(play_history.c.played_at.desc())
        .limit(SCAN)
    ).all()
    cutoff = now - REDISCOVER_AFTER_DAYS * DAY_MS
    counts: dict[tuple[str, int], int] = defaultdict(int)
    last: dict[tuple[str, int], int] = {}
    album_artist: dict[int, int] = {}
    for r in rows:
        album_artist[r.album_id] = r.album_artist_id
        # The track artist, not the album artist: "Various Artists" is nobody to rediscover.
        for item in (("album", r.album_id), ("artist", r.artist_id)):
            if item[1] is None:
                continue
            counts[item] += 1
            last[item] = max(last.get(item, 0), r.played_at)
    candidates = [(item, n) for item, n in counts.items() if n >= REDISCOVER_MIN_PLAYS and last[item] < cutoff]
    candidates.sort(key=lambda c: -c[1])
    pool = candidates[:REDISCOVER_POOL]

    rng = random.Random(f"rediscover:{user.id}:{time.strftime('%Y-%m-%d', time.gmtime(now / 1000))}")
    picked: list[tuple[str, int]] = []
    used_artists: set[int] = set()
    while pool and len(picked) < limit:
        weights = [math.log1p(n) for _, n in pool]
        i = rng.choices(range(len(pool)), weights=weights)[0]
        (kind, item_id), _ = pool.pop(i)
        artist_id = item_id if kind == "artist" else album_artist.get(item_id)
        if artist_id in used_artists:
            continue
        used_artists.add(artist_id)
        picked.append((kind, item_id))

    ids = {"album": [i for k, i in picked if k == "album"], "artist": [i for k, i in picked if k == "artist"]}
    album_rows = {r.id: r for r in fetch_ordered(conn, album_select(), albums.c.id, ids["album"])}
    artist_rows = {r.id: r for r in fetch_ordered(conn, artist_select(), artists.c.id, ids["artist"])}
    out = []
    for kind, item_id in picked:
        if kind == "album" and (a := album_rows.get(item_id)):
            out.append({"type": "album", "id": a.id, "name": a.title, "subtitle": a.artist_name, "cover": a.cover})
        elif kind == "artist" and (r := artist_rows.get(item_id)):
            # Always a picture (fallback_cover), like a radio: the card's colours come from it.
            out.append(
                {"type": "artist", "id": r.id, "name": r.name, "subtitle": "Künstler", "cover": r.fallback_cover}
            )
        else:
            continue
        out[-1]["last_played"] = last[(kind, item_id)]
    return out
