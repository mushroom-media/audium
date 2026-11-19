"""Similar artists from ListenBrainz: "fans of X also listen to Y", stored per artist.

Only while the source "artists" is on (analysis/sources.py, off by default). For each artist of
the library its MusicBrainz id goes to labs.api.listenbrainz.org; artists without one in the
tags are looked up by name at musicbrainz.org first. Nothing about the users (plays, favorites)
leaves the server. The answer is reduced to artists that are in the library (by MusicBrainz id,
else by name) and stored in artist_similar.

Runs as small jobs on the scan worker: BATCH artists per job, about one request per second (the
services ask for that), most tracks first. Answers are refreshed after REFRESH_MS, failed
requests retried after RETRY_MS.
"""

import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable

from sqlalchemy import Connection, delete, func, insert, or_, select, update

from audium import __version__
from audium.analysis import sources
from audium.db.engine import Database
from audium.db.schema import artist_similar, artist_similar_status, artists
from audium.jobs import queue as jobq
from audium.logging import get_logger
from audium.util import norm, now_ms

log = get_logger(__name__)

LB_URL = "https://labs.api.listenbrainz.org/similar-artists/json"
LB_ALGORITHM = "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"
MB_URL = "https://musicbrainz.org/ws/2/artist/"
USER_AGENT = f"audium/{__version__} (self-hosted music server)"
JOB_QUEUE = "scan"
JOB_TYPE = "similar_artists"
BATCH = 20
REFRESH_MS = 90 * 86_400_000
RETRY_MS = 86_400_000
_PAUSE_S = 1.1
_TIMEOUT_S = 20
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

Fetch = Callable[[str], list[tuple[str, str, float]]]
Lookup = Callable[[str], str | None]


def _get_json(url: str, params: dict) -> object:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310 - fixed https URLs
        return json.loads(resp.read())


def fetch_similar(mbid: str) -> list[tuple[str, str, float]]:
    """[(mbid, name, score)] of the artists ListenBrainz listeners play together with `mbid`."""
    data = _get_json(LB_URL, {"artist_mbids": mbid, "algorithm": LB_ALGORITHM})
    if not isinstance(data, list):
        return []
    return [
        (d["artist_mbid"], d.get("name") or "", float(d.get("score") or 0))
        for d in data
        if isinstance(d, dict) and isinstance(d.get("artist_mbid"), str)
    ]


def lookup_mbid(name: str) -> str | None:
    """The MusicBrainz id of an artist name, only for an exact (case/accent-insensitive) match."""
    data = _get_json(MB_URL, {"query": f'artist:"{name}"', "fmt": "json", "limit": 3})
    for a in data.get("artists", []) if isinstance(data, dict) else []:
        if a.get("score") == 100 and norm(a.get("name") or "") == norm(name) and _UUID.fullmatch(a.get("id") or ""):
            return a["id"]
    return None


def mbid_of(tag: str | None) -> str | None:
    """The first MusicBrainz id in a tag value (multi-artist tags hold several)."""
    m = _UUID.search((tag or "").lower())
    return m.group(0) if m else None


def _due(now: int):
    s = artist_similar_status.c
    return or_(
        s.artist_id.is_(None),
        (s.status != "error") & (s.fetched_at < now - REFRESH_MS),
        (s.status == "error") & (s.fetched_at < now - RETRY_MS),
    )


def pending(conn: Connection, limit: int, now: int | None = None) -> list[tuple[int, str, str | None]]:
    """[(artist id, name, MusicBrainz id from the tags)] to ask for next, most tracks first."""
    now = now_ms() if now is None else now
    rows = conn.execute(
        select(artists.c.id, artists.c.name, artists.c.mb_artist_id)
        .outerjoin(artist_similar_status, artist_similar_status.c.artist_id == artists.c.id)
        .where(artists.c.track_count > 0, _due(now))
        .order_by(artists.c.track_count.desc(), artists.c.id)
        .limit(limit)
    ).all()
    return [(r.id, r.name, mbid_of(r.mb_artist_id)) for r in rows]


def count_pending(conn: Connection) -> int:
    return conn.execute(
        select(func.count())
        .select_from(artists.outerjoin(artist_similar_status, artist_similar_status.c.artist_id == artists.c.id))
        .where(artists.c.track_count > 0, _due(now_ms()))
    ).scalar_one()


def _library(conn: Connection) -> tuple[dict[str, int], dict[str, int]]:
    """Library artists by MusicBrainz id (tags and looked up) and by normalized name."""
    by_mbid: dict[str, int] = {}
    for r in conn.execute(select(artists.c.id, artists.c.mb_artist_id).where(artists.c.mb_artist_id.is_not(None))):
        if mbid := mbid_of(r.mb_artist_id):
            by_mbid.setdefault(mbid, r.id)
    for r in conn.execute(
        select(artist_similar_status.c.artist_id, artist_similar_status.c.mbid).where(
            artist_similar_status.c.mbid.is_not(None)
        )
    ):
        by_mbid.setdefault(r.mbid, r.artist_id)
    by_name = dict(conn.execute(select(artists.c.name_norm, artists.c.id)).tuples().all())
    return by_mbid, by_name


def store(conn: Connection, artist_id: int, mbid: str | None, status: str, found: list[tuple[str, str, float]]) -> int:
    """Replace the artist's similar artists with those of `found` that are in the library."""
    conn.execute(delete(artist_similar_status).where(artist_similar_status.c.artist_id == artist_id))
    conn.execute(
        insert(artist_similar_status).values(artist_id=artist_id, mbid=mbid, status=status, fetched_at=now_ms())
    )
    if status == "error":
        return 0  # keep the last good answer
    conn.execute(delete(artist_similar).where(artist_similar.c.artist_id == artist_id))
    top = max((score for _m, _n, score in found), default=0.0) or 1.0
    by_mbid, by_name = _library(conn)
    scores: dict[int, float] = {}
    for other_mbid, name, score in found:
        other = by_mbid.get(other_mbid) or by_name.get(norm(name))
        if other is not None and other != artist_id:
            scores[other] = max(scores.get(other, 0.0), score / top)
    if scores:
        conn.execute(
            insert(artist_similar), [{"artist_id": artist_id, "similar_id": o, "score": s} for o, s in scores.items()]
        )
    return len(scores)


def run_batch(
    db: Database,
    batch: int = BATCH,
    fetch: Fetch = fetch_similar,
    lookup: Lookup = lookup_mbid,
    pause: Callable[[float], None] = time.sleep,
) -> dict:
    """Ask for the next `batch` artists. The requests run outside of any transaction."""
    with db.read() as conn:
        todo = pending(conn, batch)
    stats = {"artists": 0, "matched": 0, "no_mbid": 0, "errors": 0}
    for i, (artist_id, name, mbid) in enumerate(todo):
        if i:
            pause(_PAUSE_S)
        status, found = "ok", []
        try:
            if mbid is None:
                mbid = lookup(name)
                pause(_PAUSE_S)
            if mbid is None:
                status = "no_mbid"
            else:
                found = fetch(mbid)
        except Exception as e:  # network, HTTP 429/5xx, bad JSON: try again another day
            log.warning("similar_artists.request_failed", artist=name, error=str(e))
            status = "error"
        with db.write() as conn:
            matched = store(conn, artist_id, mbid, status, found)
        stats["artists"] += 1
        stats["matched"] += matched
        stats["no_mbid"] += status == "no_mbid"
        stats["errors"] += status == "error"
    with db.read() as conn:
        stats["left"] = count_pending(conn)
    return stats


def enabled(conn: Connection) -> bool:
    return sources.load(conn)["artists"].on


def refresh_all(conn: Connection) -> None:
    """Ask for every artist again; the last good answers stay until the new ones are in."""
    conn.execute(update(artist_similar_status).values(fetched_at=0))
    enqueue(conn)


def enqueue(conn: Connection, delay_ms: int = 0) -> int:
    return jobq.enqueue(conn, JOB_QUEUE, JOB_TYPE, dedupe_key="similar-artists", delay_ms=delay_ms)


def similar_to(conn: Connection, artist_ids: list[int], limit: int = 50) -> list[tuple[int, float, int]]:
    """[(similar artist, score, via which of `artist_ids`)] best first, the group itself left out."""
    if not artist_ids:
        return []
    rows = conn.execute(
        select(artist_similar.c.similar_id, artist_similar.c.score, artist_similar.c.artist_id)
        .where(artist_similar.c.artist_id.in_(artist_ids), artist_similar.c.similar_id.not_in(artist_ids))
        .order_by(artist_similar.c.score.desc())
    ).all()
    out: dict[int, tuple[float, int]] = {}
    for similar_id, score, via in rows:
        if similar_id not in out:
            out[similar_id] = (score, via)
    return [(a, s, v) for a, (s, v) in list(out.items())[:limit]]
