"""Similar tracks and "radio" by distance between track vectors.

Two vector spaces, the better one wins per track:
- fingerprints (Discogs-EffNet embeddings, 1280 values) where the analysis had the models: they
  capture instrumentation, production and style far better than a handful of numbers. Reduced
  by PCA to EMBEDDING_DIMS and compared by cosine distance (100k x 128 float32 = 51 MB).
- the ~10 hand-made descriptors (BPM, energy, ...) otherwise (100k x 9 float32 = 3.6 MB).

A brute-force distance over the whole matrix takes a few milliseconds, so no vector index is
needed. The matrices are rebuilt when the analysis worker reports new results (state key
ANALYSIS_GENERATION), in the background; the fingerprints at most every EMBEDDING_REFRESH_S
while it is busy.

Without analysis (e.g. arm64 without Essentia) a fallback uses genre, year and artist.
"""

import threading
import time
from collections.abc import Collection, Iterable

import numpy as np
from sqlalchemy import Connection, case, func, literal, select

from audium.analysis.features import EMBEDDING_MODEL
from audium.db.engine import Database
from audium.db.schema import track_embeddings, track_features, track_genres, tracks
from audium.db.state import get_state
from audium.logging import get_logger

log = get_logger(__name__)

ANALYSIS_GENERATION = "analysis.generation"
VECTOR_FIELDS = ("bpm", "energy", "danceability", "brightness", "dynamics", "mode",
                 "mood_happy", "mood_sad", "mood_aggressive", "mood_relaxed")  # fmt: skip
# Relative importance in the distance (after standardizing every column).
_WEIGHTS = {"bpm": 1.2, "energy": 1.3, "danceability": 1.0, "brightness": 0.8, "dynamics": 0.6, "mode": 0.4,
            "mood_happy": 0.8, "mood_sad": 0.8, "mood_aggressive": 0.8, "mood_relaxed": 0.8}  # fmt: skip
EMBEDDING_SIZE = 1280
EMBEDDING_DIMS = 128
EMBEDDING_REFRESH_S = 600
_PCA_SAMPLE = 20_000
_CHUNK = 2000


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


def _embeddings_select():
    return (
        select(track_embeddings.c.track_id, track_embeddings.c.vector)
        .join(tracks, tracks.c.id == track_embeddings.c.track_id)
        .where(
            track_embeddings.c.model == EMBEDDING_MODEL,
            track_embeddings.c.vector.is_not(None),
            tracks.c.missing_since.is_(None),
        )
        .order_by(track_embeddings.c.track_id)
    )


def _decode(blobs: list[bytes]) -> np.ndarray:
    return np.frombuffer(b"".join(blobs), dtype=np.float16).reshape(len(blobs), EMBEDDING_SIZE).astype(np.float32)


def embedding_matrix(conn: Connection, dims: int = EMBEDDING_DIMS) -> tuple[np.ndarray, np.ndarray]:
    """(track ids, unit-length PCA-reduced fingerprints) of all present tracks that have one. The
    PCA is fitted on a sample, then the library is projected chunk by chunk, so the full
    1280-wide matrix is never in memory."""
    stmt = _embeddings_select()
    ids = conn.execute(stmt.with_only_columns(track_embeddings.c.track_id)).scalars().all()
    if len(ids) < 2:
        return np.empty(0, dtype=np.int64), np.empty((0, 0), dtype=np.float32)
    sample = ids
    if len(ids) > _PCA_SAMPLE:
        sample = sorted(np.random.default_rng(0).choice(ids, _PCA_SAMPLE, replace=False).tolist())
    blobs = []
    for i in range(0, len(sample), _CHUNK):
        part = sample[i : i + _CHUNK]
        blobs += [r.vector for r in conn.execute(stmt.where(track_embeddings.c.track_id.in_(part)))]
    s = _decode(blobs)
    mean = s.mean(axis=0)
    _u, _sv, vt = np.linalg.svd(s - mean, full_matrices=False)
    proj = vt[:dims].T.astype(np.float32)
    out_ids: list[int] = []
    parts: list[np.ndarray] = []
    chunk_ids: list[int] = []
    blobs = []
    for r in conn.execute(stmt):
        chunk_ids.append(r.track_id)
        blobs.append(r.vector)
        if len(blobs) == _CHUNK:
            parts.append((_decode(blobs) - mean) @ proj)
            out_ids += chunk_ids
            chunk_ids, blobs = [], []
    if blobs:
        parts.append((_decode(blobs) - mean) @ proj)
        out_ids += chunk_ids
    z = np.vstack(parts)
    norms = np.linalg.norm(z, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return np.array(out_ids, dtype=np.int64), (z / norms).astype(np.float32)


class _Space:
    """One matrix of track vectors and how to measure distance in it."""

    def __init__(self, ids: np.ndarray, z: np.ndarray, cosine: bool) -> None:
        self.ids, self.z, self.cosine = ids, z, cosine
        self.pos = {int(t): i for i, t in enumerate(ids)}

    def nearest(self, rows: list[int], k: int) -> list[tuple[int, float]] | None:
        """[(track_id, distance)] nearest to the mean of the given rows (left out), nearest first."""
        if not rows or len(self.ids) <= len(rows):
            return None
        v = self.z[rows].mean(axis=0)
        if self.cosine:  # noqa: SIM108 - rows are unit length
            d = 1.0 - self.z @ (v / (np.linalg.norm(v) or 1.0))
        else:
            d = np.sqrt(((self.z - v) ** 2).sum(axis=1))
        d[rows] = np.inf
        k = min(k, len(self.ids) - len(rows))
        idx = np.argpartition(d, k)[:k]
        idx = idx[np.argsort(d[idx])]
        return [(int(self.ids[j]), float(d[j])) for j in idx]


_EMPTY = _Space(np.empty(0, dtype=np.int64), np.empty((0, 0), dtype=np.float32), cosine=False)


class VectorIndex:
    """Per-process cache of both vector spaces, refreshed when the analysis generation changes.

    With a database, only the first load happens inside a request: later reloads (seconds for a
    large library) run in a background thread while requests keep using the previous matrices."""

    def __init__(self, db: Database | None = None, embedding_refresh_s: float = EMBEDDING_REFRESH_S) -> None:
        self._db = db
        self._lock = threading.Lock()
        self._loaded = False
        self._refreshing = False
        self._generation: str | None = None
        self._features = _EMPTY
        self._embeddings = _EMPTY
        self._embeddings_generation: str | None = None
        self._embeddings_at: float | None = None
        self._embedding_refresh_s = embedding_refresh_s

    def warm(self) -> None:
        """Load both spaces in the background, so the first radio after a start does not wait."""
        if self._db is None:
            return
        with self._lock:
            if self._loaded or self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh_in_background, name="vector-index", daemon=True).start()

    def _stale(self, generation: str) -> tuple[bool, bool]:
        """(features, embeddings) need a reload; call with the lock held."""
        stale_features = generation != self._generation
        # Fingerprints are expensive to load: while the analysis keeps reporting, at most every
        # EMBEDDING_REFRESH_S (a reload put off this way happens on a later request).
        stale_embeddings = generation != self._embeddings_generation and (
            self._embeddings_at is None or time.monotonic() - self._embeddings_at >= self._embedding_refresh_s
        )
        return stale_features, stale_embeddings

    def _refresh(self, conn: Connection) -> None:
        generation = get_state(conn, ANALYSIS_GENERATION) or "0"
        with self._lock:
            stale_features, stale_embeddings = self._stale(generation)
        if stale_features:
            ids, z, _names = feature_matrix(conn)
            features = _Space(ids, z, cosine=False)
            with self._lock:
                self._features, self._generation = features, generation
        if stale_embeddings:
            embeddings = _Space(*embedding_matrix(conn), cosine=True)
            with self._lock:
                self._embeddings, self._embeddings_generation = embeddings, generation
                self._embeddings_at = time.monotonic()
        with self._lock:
            self._loaded = True

    def _refresh_in_background(self) -> None:
        try:
            with self._db.read() as conn:
                self._refresh(conn)
        except Exception:
            log.exception("vectors.refresh_failed")
        finally:
            with self._lock:
                self._refreshing = False

    def _spaces(self, conn: Connection) -> tuple[_Space, _Space]:
        """(fingerprints, descriptors), the better space first."""
        generation = get_state(conn, ANALYSIS_GENERATION) or "0"
        with self._lock:
            stale = any(self._stale(generation))
            background = stale and self._db is not None and self._loaded
            if background and not self._refreshing:
                self._refreshing = True
                threading.Thread(target=self._refresh_in_background, name="vector-index", daemon=True).start()
        if stale and not background:
            self._refresh(conn)
        with self._lock:
            return self._embeddings, self._features

    def nearest(self, conn: Connection, track_id: int, k: int) -> list[tuple[int, float]] | None:
        """[(track_id, distance)] nearest first, or None if the track has no vector."""
        for space in self._spaces(conn):
            i = space.pos.get(track_id)
            if i is not None:
                return space.nearest([i], k)
        return None

    def nearest_to_group(self, conn: Connection, track_ids: Iterable[int], k: int) -> list[tuple[int, float]] | None:
        """Nearest to the mean vector of several tracks (an album, an artist), the group itself left
        out. None if none of them has a vector."""
        track_ids = list(track_ids)
        for space in self._spaces(conn):
            rows = sorted({space.pos[t] for t in track_ids if t in space.pos})
            if rows:
                return space.nearest(rows, k)
        return None


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


def fallback_group(conn: Connection, track_ids: Collection[int], k: int) -> list[int]:
    """Without audio features, for several tracks: the group's most common genres first, then the
    same decade (around the group's median year)."""
    weights: dict[int, int] = {}
    for genre_id, n in conn.execute(
        select(track_genres.c.genre_id, func.count())
        .where(track_genres.c.track_id.in_(track_ids))
        .group_by(track_genres.c.genre_id)
    ):
        weights[genre_id] = n
    years = sorted(y for (y,) in conn.execute(select(tracks.c.year).where(tracks.c.id.in_(track_ids))) if y)
    year = years[len(years) // 2] if years else None
    if not weights and year is None:
        return []
    score = literal(0)
    if weights:
        shared = select(func.sum(case(weights, value=track_genres.c.genre_id, else_=0))).where(
            track_genres.c.track_id == tracks.c.id
        )
        score = func.coalesce(shared.scalar_subquery(), 0)
    year_gap = func.abs(tracks.c.year - year) if year is not None else literal(0)
    near_year = (tracks.c.year > 0) & (year_gap <= 5) if year is not None else literal(False)
    rows = conn.execute(
        select(tracks.c.id)
        .where(tracks.c.id.not_in(track_ids), tracks.c.missing_since.is_(None), (score > 0) | near_year)
        .order_by(score.desc(), year_gap, (tracks.c.id * 2654435761) % 4294967296)
        .limit(k)
    ).all()
    return [r[0] for r in rows]


def _sample(conn: Connection, candidates: list[int], n: int, rng: np.random.Generator) -> list[int]:
    """Up to n of the candidates (nearest first): rank-weighted sampling without replacement, so
    near tracks are likely and far ones possible, at most two tracks per album."""
    if not candidates or n <= 0:
        return []
    weights = 1.0 / (np.arange(len(candidates)) + 8.0)
    order = rng.choice(len(candidates), size=len(candidates), replace=False, p=weights / weights.sum())
    albums_seen: dict[int, int] = {}
    album_of = dict(conn.execute(select(tracks.c.id, tracks.c.album_id).where(tracks.c.id.in_(candidates))).all())
    out: list[int] = []
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


def radio(
    conn: Connection,
    index: VectorIndex,
    track_id: int,
    n: int,
    rng: np.random.Generator,
    exclude: Collection[int] = (),
) -> list[int]:
    """A station from one track: mostly close neighbours, a few further ones for variety, at most
    two tracks per album and never the same track twice. `exclude`: tracks the station already
    played (continuing it); then it does not start with the seed again."""
    skip = set(exclude)
    k = max(n * 4, 200) + len(skip)
    near = index.nearest(conn, track_id, k)
    candidates = [t for t, _ in near] if near else fallback_similar(conn, track_id, k)
    candidates = [t for t in candidates if t not in skip]
    if track_id in skip:
        return _sample(conn, candidates, n, rng)
    return [track_id, *_sample(conn, candidates, n - 1, rng)]


OWN_SHARE = 0.25  # of a group station: the album's/artist's own tracks, the rest is similar music


def group_radio(
    conn: Connection,
    index: VectorIndex,
    track_ids: list[int],
    n: int,
    rng: np.random.Generator,
    exclude: Collection[int] = (),
) -> list[int]:
    """A station from an album or artist: tracks close to the group's average sound (or its genres
    and decade without analysis), with about a quarter of the group's own tracks spread over it.
    Starts with one of the own tracks. `exclude`: tracks the station already played; once all own
    tracks were, they may come again."""
    skip = set(exclude)
    pool = [t for t in track_ids if t not in skip] or track_ids
    own = [int(t) for t in rng.permutation(pool)[: max(1, round(n * OWN_SHARE))]]
    k = max(n * 4, 200) + len(skip)
    near = index.nearest_to_group(conn, track_ids, k)
    candidates = [t for t, _ in near] if near else fallback_group(conn, track_ids, k)
    others = _sample(conn, [t for t in candidates if t not in skip], n - len(own), rng)
    if not others:
        return own
    # Own tracks at evenly spaced positions, the first one at the start.
    total = len(own) + len(others)
    own_at = {round(i * total / len(own)) for i in range(len(own))}
    own_it, others_it = iter(own), iter(others)
    return [next(own_it) if i in own_at else next(others_it) for i in range(total)]
