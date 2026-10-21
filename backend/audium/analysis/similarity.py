"""Similar tracks and "radio" by distance between feature vectors.

All analysed tracks fit into one numpy matrix (100k x 9 float32 = 3.6 MB). A brute-force
distance over it takes a few milliseconds, so no vector index is needed. The matrix is rebuilt
when the analysis worker reports new results (state key ANALYSIS_GENERATION).

Without analysis (e.g. arm64 without Essentia) a fallback uses genre, year and artist.
"""

import threading

import numpy as np
from sqlalchemy import Connection, func, select

from audium.db.schema import track_features, track_genres, tracks
from audium.db.state import get_state

ANALYSIS_GENERATION = "analysis.generation"
VECTOR_FIELDS = ("bpm", "energy", "danceability", "brightness", "dynamics", "mode",
                 "mood_happy", "mood_sad", "mood_aggressive", "mood_relaxed")  # fmt: skip
# Relative importance in the distance (after standardizing every column).
_WEIGHTS = {"bpm": 1.2, "energy": 1.3, "danceability": 1.0, "brightness": 0.8, "dynamics": 0.6, "mode": 0.4,
            "mood_happy": 0.8, "mood_sad": 0.8, "mood_aggressive": 0.8, "mood_relaxed": 0.8}  # fmt: skip


def feature_matrix(conn: Connection) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """(track ids, standardized weighted matrix, used column names) of all present, analysed tracks."""
    cols = [track_features.c[f] for f in VECTOR_FIELDS if f != "mode"]
    rows = conn.execute(
        select(track_features.c.track_id, track_features.c.mode, *cols)
        .join(tracks, tracks.c.id == track_features.c.track_id)
        .where(track_features.c.status == "ok", tracks.c.missing_since.is_(None))
        .order_by(track_features.c.track_id)
    ).all()
    if not rows:
        return np.empty(0, dtype=np.int64), np.empty((0, 0), dtype=np.float32), []
    ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
    names = ["mode", *[c.name for c in cols]]
    raw = np.array(
        [[1.0 if r[1] == "major" else 0.0, *[np.nan if v is None else float(v) for v in r[2:]]] for r in rows],
        dtype=np.float32,
    )
    keep = ~np.isnan(raw).all(axis=0)  # drop columns nobody has (moods without ML models)
    raw, names = raw[:, keep], [n for n, k in zip(names, keep, strict=True) if k]
    mean = np.nanmean(raw, axis=0)
    std = np.nanstd(raw, axis=0)
    std[std == 0] = 1
    z = np.nan_to_num((raw - mean) / std)
    z *= np.array([_WEIGHTS[n] for n in names], dtype=np.float32)
    return ids, z.astype(np.float32), names


class VectorIndex:
    """Per-process cache of the feature matrix, refreshed when the analysis generation changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation: str | None = None
        self._ids = np.empty(0, dtype=np.int64)
        self._z = np.empty((0, 0), dtype=np.float32)
        self._pos: dict[int, int] = {}

    def _refresh(self, conn: Connection) -> None:
        generation = get_state(conn, ANALYSIS_GENERATION) or "0"
        with self._lock:
            if generation == self._generation:
                return
        ids, z, _names = feature_matrix(conn)
        with self._lock:
            self._ids, self._z, self._generation = ids, z, generation
            self._pos = {int(t): i for i, t in enumerate(ids)}

    def nearest(self, conn: Connection, track_id: int, k: int) -> list[tuple[int, float]] | None:
        """[(track_id, distance)] nearest first, or None if the track has no features."""
        self._refresh(conn)
        with self._lock:
            ids, z, pos = self._ids, self._z, self._pos
        i = pos.get(track_id)
        if i is None or len(ids) < 2:
            return None
        d = np.sqrt(((z - z[i]) ** 2).sum(axis=1))
        d[i] = np.inf
        k = min(k, len(ids) - 1)
        idx = np.argpartition(d, k)[:k]
        idx = idx[np.argsort(d[idx])]
        return [(int(ids[j]), float(d[j])) for j in idx]


def fallback_similar(conn: Connection, track_id: int, k: int) -> list[int]:
    """Without audio features: same genre and a similar year first, then the same artist."""
    me = conn.execute(
        select(tracks.c.artist_id, tracks.c.year, tracks.c.album_id).where(tracks.c.id == track_id)
    ).first()
    if me is None:
        return []
    my_genres = select(track_genres.c.genre_id).where(track_genres.c.track_id == track_id)
    shared = (
        select(track_genres.c.track_id, func.count().label("n"))
        .where(track_genres.c.genre_id.in_(my_genres))
        .group_by(track_genres.c.track_id)
        .subquery()
    )
    year_gap = func.abs(tracks.c.year - (me.year or 0))
    rows = conn.execute(
        select(tracks.c.id)
        .outerjoin(shared, shared.c.track_id == tracks.c.id)
        .where(
            tracks.c.id != track_id,
            tracks.c.missing_since.is_(None),
            (shared.c.n.is_not(None)) | (tracks.c.artist_id == me.artist_id),
        )
        .order_by(
            func.coalesce(shared.c.n, 0).desc(),
            year_gap,
            (tracks.c.artist_id == me.artist_id).desc(),
            (tracks.c.id * 2654435761) % 4294967296,
        )
        .limit(k)
    ).all()
    return [r[0] for r in rows]


def radio(conn: Connection, index: VectorIndex, track_id: int, n: int, rng: np.random.Generator) -> list[int]:
    """A station from one track: mostly close neighbours, a few further ones for variety, at most
    two tracks per album and never the same track twice."""
    near = index.nearest(conn, track_id, max(n * 4, 200))
    candidates = [t for t, _ in near] if near else fallback_similar(conn, track_id, n * 4)
    if not candidates:
        return [track_id]
    # Rank-weighted sampling without replacement: near tracks are likely, far ones possible.
    weights = 1.0 / (np.arange(len(candidates)) + 8.0)
    order = rng.choice(len(candidates), size=len(candidates), replace=False, p=weights / weights.sum())
    albums_seen: dict[int, int] = {}
    album_of = dict(
        conn.execute(select(tracks.c.id, tracks.c.album_id).where(tracks.c.id.in_(candidates[: n * 4]))).all()
    )
    out = [track_id]
    for j in order:
        t = candidates[j]
        album = album_of.get(t)
        if albums_seen.get(album, 0) >= 2:
            continue
        albums_seen[album] = albums_seen.get(album, 0) + 1
        out.append(t)
        if len(out) >= n:
            break
    return out
