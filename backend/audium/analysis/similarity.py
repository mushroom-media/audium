"""Similar tracks and "radio" by distance between track vectors.

Two vector spaces, the better one wins per track:
- fingerprints (Discogs-EffNet embeddings, 1280 values) where the analysis had the models: they
  capture instrumentation, production and style far better than a handful of numbers. Reduced
  by PCA to EMBEDDING_DIMS and compared by cosine distance (100k x 128 float32 = 51 MB).
- the ~10 hand-made descriptors (BPM, energy, ...) otherwise (100k x 9 float32 = 3.6 MB).

A brute-force distance over the whole matrix takes a few milliseconds, so no vector index is
needed. The matrices are rebuilt when the analysis worker reports new results (state key
ANALYSIS_GENERATION), in the background; the fingerprints at most every EMBEDDING_REFRESH_S
while it is busy. Building the fingerprint matrix takes minutes at 100k tracks and would keep the
API from answering (it holds the GIL, and a read holds the API's only read slot), so the server
builds in a process of its own (analysis/vector_build.py) and keeps the result in files: after a
restart the matrices are there within a second, and a stale file serves until the new one is ready.

Without analysis (e.g. arm64 without Essentia) a fallback uses genre, year and artist.

Stations (radio, group_radio) and "similar tracks" blend several sources by the admin's
switches and weights (analysis/sources.py, blend below): the two vector spaces, genre/year and
similar artists from ListenBrainz, and per listener their taste and skips (analysis/taste.py).
"""

import os
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sqlalchemy import Connection, case, func, literal, select

from audium.analysis import sources, taste
from audium.analysis.features import EMBEDDING_MODEL
from audium.db.engine import Database
from audium.db.schema import track_artists, track_embeddings, track_features, track_genres, tracks
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
_BUILD_RETRY_S = 60
_BUILD_TIMEOUT_S = 3600
_BUILD_THREADS = "2"  # the linear algebra would otherwise spin on every core, next to playback and the API
VECTOR_DB_ENV = "AUDIUM_VECTOR_DB_URL"  # not on the command line: it may hold a password


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
        self.pos = dict(zip(ids.tolist(), range(len(ids)), strict=True))

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


def _load_space(path: Path, cosine: bool) -> tuple[_Space, str, float] | None:
    """(space, generation it was built for, when it was built) of a file; None without a usable one."""
    try:
        with np.load(path) as data:
            return _Space(data["ids"], data["z"], cosine), str(data["generation"]), path.stat().st_mtime
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return None


def _save_space(path: Path, ids: np.ndarray, z: np.ndarray, generation: str) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        np.savez(f, ids=ids, z=z, generation=np.array(generation))
    os.replace(tmp, path)


def build_files(db: Database, directory: Path, wanted: Iterable[str]) -> None:
    """Writes the matrices in `wanted` ("features", "embeddings"), each for the generation it read."""
    directory.mkdir(parents=True, exist_ok=True)
    for what in wanted:
        with db.read() as conn:
            generation = get_state(conn, ANALYSIS_GENERATION) or "0"
            if what == "features":
                ids, z, _names = feature_matrix(conn)
            else:
                ids, z = embedding_matrix(conn)
        _save_space(directory / f"{what}.npz", ids, z, generation)


class VectorIndex:
    """Per-process cache of both vector spaces, refreshed when the analysis generation changes.

    With a database, only the first load happens inside a request: later reloads (seconds for a
    large library) run in a background thread while requests keep using the previous matrices.
    With `directory` too (the server), no load happens in a request at all: until the files are
    there requests see empty spaces and the stations fall back to genre and year."""

    def __init__(
        self,
        db: Database | None = None,
        embedding_refresh_s: float = EMBEDDING_REFRESH_S,
        directory: Path | None = None,
    ) -> None:
        self._db = db
        self._directory = directory
        self._retry_at = 0.0
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

    def _load_files(self, wanted: Iterable[str]) -> None:
        for what in wanted:
            loaded = _load_space(self._directory / f"{what}.npz", cosine=what == "embeddings")
            if loaded is None:
                continue
            space, generation, built = loaded
            with self._lock:
                if what == "features":
                    self._features, self._generation = space, generation
                else:
                    self._embeddings, self._embeddings_generation = space, generation
                    # Across a restart too: a fresh file does not need rebuilding right away.
                    self._embeddings_at = time.monotonic() - max(0.0, time.time() - built)

    def _refresh_files(self) -> None:
        with self._lock:
            first = not self._loaded
        if first:
            self._load_files(("features", "embeddings"))
            with self._lock:
                self._loaded = True
        with self._db.read() as conn:
            generation = get_state(conn, ANALYSIS_GENERATION) or "0"
        with self._lock:
            stale_features, stale_embeddings = self._stale(generation)
        wanted = [w for w, stale in (("features", stale_features), ("embeddings", stale_embeddings)) if stale]
        if not wanted:
            return
        subprocess.run(
            [sys.executable, "-m", "audium.analysis.vector_build", str(self._directory), *wanted],
            env={
                **os.environ,
                VECTOR_DB_ENV: self._db.url,
                "OPENBLAS_NUM_THREADS": _BUILD_THREADS,
                "OMP_NUM_THREADS": _BUILD_THREADS,
            },
            check=True,
            timeout=_BUILD_TIMEOUT_S,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._load_files(wanted)

    def _refresh_in_background(self) -> None:
        try:
            if self._directory is not None:
                self._refresh_files()
            else:
                with self._db.read() as conn:
                    self._refresh(conn)
        except Exception as e:
            log.exception("vectors.refresh_failed", stderr=getattr(e, "stderr", None))
            self._retry_at = time.monotonic() + _BUILD_RETRY_S
        finally:
            with self._lock:
                self._refreshing = False

    def _spaces(self, conn: Connection) -> tuple[_Space, _Space]:
        """(fingerprints, descriptors), the better space first."""
        generation = get_state(conn, ANALYSIS_GENERATION) or "0"
        with self._lock:
            stale = any(self._stale(generation))
            background = stale and self._db is not None and (self._loaded or self._directory is not None)
            if background and not self._refreshing and time.monotonic() >= self._retry_at:
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

    def nearest_in(
        self, conn: Connection, space: str, track_ids: Iterable[int], k: int
    ) -> list[tuple[int, float]] | None:
        """Like nearest_to_group, in one space only: "sound" (fingerprints) or "features"."""
        embeddings, features = self._spaces(conn)
        s = embeddings if space == "sound" else features
        rows = sorted({s.pos[t] for t in track_ids if t in s.pos})
        return s.nearest(rows, k) if rows else None


def fallback_similar(conn: Connection, track_id: int, k: int) -> list[int]:
    """Without audio features: same genre and a similar year first, then the same artist. The
    year only orders: a track has to share a genre (from the tags or detected) or the artist."""
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
    same decade (around the group's median year). As for one track, the year alone never makes a
    candidate: it has to share a genre or an artist with the group."""
    weights: dict[int, int] = {}
    for genre_id, n in conn.execute(
        select(track_genres.c.genre_id, func.count())
        .where(track_genres.c.track_id.in_(track_ids))
        .group_by(track_genres.c.genre_id)
    ):
        weights[genre_id] = n
    years = sorted(y for (y,) in conn.execute(select(tracks.c.year).where(tracks.c.id.in_(track_ids))) if y)
    year = years[len(years) // 2] if years else None
    group_artists = select(tracks.c.artist_id).where(tracks.c.id.in_(track_ids)).distinct()
    score = literal(0)
    if weights:
        shared = select(func.sum(case(weights, value=track_genres.c.genre_id, else_=0))).where(
            track_genres.c.track_id == tracks.c.id
        )
        score = func.coalesce(shared.scalar_subquery(), 0)
    year_gap = func.abs(tracks.c.year - year) if year is not None else literal(0)
    rows = conn.execute(
        select(tracks.c.id)
        .where(
            tracks.c.id.not_in(track_ids),
            tracks.c.missing_since.is_(None),
            (score > 0) | tracks.c.artist_id.in_(group_artists),
        )
        .order_by(score.desc(), year_gap, (tracks.c.id * 2654435761) % 4294967296)
        .limit(k)
    ).all()
    return [r[0] for r in rows]


# --- several sources blended (analysis/sources.py) -------------------------------------------

# Why a track is in a station: source -> its share of the track's score (sources' shares sum to
# 1, so this is at most 1). Also "seed" (the start track), "own" (the album's/artist's own
# tracks) and "fallback" (genre/year when none of the chosen sources found anything).
# "taste" only ever adds to tracks another source found.
Why = dict[str, float]
_SEED_ARTISTS = 5
# Every source ranks at least this many candidates: a track at rank r scores (1 - r / depth), so
# asking for only a few tracks does not make rank 10 worth next to nothing.
_DEPTH = 200
_PER_ARTIST = 30


@dataclass
class Blend:
    picks: list[tuple[int, Why]]  # best first
    via: dict[int, int] = field(default_factory=dict)  # track -> seed artist (source "artists")
    skipped: dict[int, float] = field(default_factory=dict)  # track -> factor its score got for skips


def _artist_candidates(conn: Connection, seeds: list[int], k: int) -> tuple[list[int], dict[int, int]]:
    """Tracks of artists whose fans listen to the seeds' artists (ListenBrainz), the closest
    artists first, taking turns between them."""
    from audium.services.similar_artists import similar_to

    counts = conn.execute(
        select(track_artists.c.artist_id, func.count())
        .where(track_artists.c.track_id.in_(seeds), track_artists.c.role == "main")
        .group_by(track_artists.c.artist_id)
        .order_by(func.count().desc())
        .limit(_SEED_ARTISTS)
    ).all()
    similar = similar_to(conn, [a for a, _ in counts])
    if not similar:
        return [], {}
    by_artist: dict[int, list[int]] = {}
    for artist_id, _score, _via in similar:
        by_artist[artist_id] = list(
            conn.execute(
                select(tracks.c.id)
                .join(track_artists, track_artists.c.track_id == tracks.c.id)
                .where(track_artists.c.artist_id == artist_id, tracks.c.missing_since.is_(None))
                .order_by((tracks.c.id * 2654435761) % 4294967296)
                .limit(_PER_ARTIST)
            ).scalars()
        )
    seen = set(seeds)
    out: list[int] = []
    via: dict[int, int] = {}
    for turn in range(_PER_ARTIST):
        for artist_id, _score, seed_artist in similar:
            own = by_artist[artist_id]
            if turn < len(own) and own[turn] not in seen:
                seen.add(own[turn])
                out.append(own[turn])
                via[own[turn]] = seed_artist
                if len(out) >= k:
                    return out, via
    return out, via


def blend(
    conn: Connection,
    index: VectorIndex,
    seeds: list[int],
    k: int,
    user_id: int | None = None,
    station: str | None = None,
) -> Blend:
    """Up to k candidates for a station from `seeds` (one track or a group), best first. Every
    switched-on source ranks its own candidates; a track's score is the sum over the sources of
    (source weight x how high it ranks there), so tracks several sources agree on come first.
    `user_id`: whose taste counts (source "taste"); `station` ("track:3", see taste.py): a radio,
    where that user's skips in similar stations count against a track and what they disliked in
    this one stays out."""
    shares = sources.weights(sources.load(conn))
    if user_id is None:
        shares.pop("taste", None)
    single = len(seeds) == 1
    depth = max(k, _DEPTH)
    lists: dict[str, list[int]] = {}
    via: dict[int, int] = {}
    for name in shares:
        if name == "taste":
            continue  # ranks what the others found, below
        if name in ("sound", "features"):
            near = index.nearest_in(conn, name, seeds, depth)
            lists[name] = [t for t, _ in near] if near else []
        elif name == "genre":
            lists[name] = fallback_similar(conn, seeds[0], depth) if single else fallback_group(conn, seeds, depth)
        elif name == "artists":
            lists[name], via = _artist_candidates(conn, seeds, depth)
    if not any(lists.values()):
        # Nothing from the chosen sources (e.g. sound only, but no analysis yet): genres and year
        # stand in, so a station is never empty.
        own_taste = shares.get("taste", 0.0)
        shares = {"fallback": max(1.0 - own_taste, 0.5)} | ({"taste": own_taste} if own_taste else {})
        lists = {"fallback": fallback_similar(conn, seeds[0], depth) if single else fallback_group(conn, seeds, depth)}
    if "taste" in shares and user_id is not None:
        found = list(dict.fromkeys(t for ids in lists.values() for t in ids))
        lists["taste"] = taste.taste_list(conn, user_id, found)
    skip = set(seeds) | (taste.dislikes(conn, user_id, station) if user_id is not None else set())
    scores: dict[int, Why] = {}
    for name, ids in lists.items():
        for rank, t in enumerate(ids):
            if t not in skip:
                scores.setdefault(t, {})[name] = shares[name] * (1.0 - rank / max(depth, len(ids)))
    skipped = taste.skip_penalties(conn, user_id, station, list(scores)) if user_id is not None else {}
    order = sorted(scores, key=lambda t: -sum(scores[t].values()) * skipped.get(t, 1.0))[:k]
    return Blend(
        [(t, scores[t]) for t in order],
        {t: via[t] for t in order if t in via},
        {t: skipped[t] for t in order if t in skipped},
    )


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


# Tempo: a step to the next track counts in octaves (log2 of the BPM ratio), with half and double
# time as good as the same (70 and 140 BPM fit). Of the next few tracks in line, the one closest in
# tempo comes first, so the station keeps its rank order roughly and avoids big jumps.
_TEMPO_LOOKAHEAD = 4


def _tempo_step(a: float | None, b: float | None) -> float:
    if not a or not b:
        return 0.25  # unknown: neither preferred nor avoided much
    d = abs(np.log2(b / a)) % 1.0
    return min(d, 1.0 - d)


def smooth_tempo(conn: Connection, picks: list[tuple[int, Why]], before: int | None = None) -> list[tuple[int, Why]]:
    """The picks reordered so neighbours are close in tempo; the first one stays first unless
    `before` (the track played last, when a station continues) is given."""
    ids = [t for t, _ in picks] + ([before] if before is not None else [])
    bpm = dict(
        conn.execute(
            select(track_features.c.track_id, track_features.c.bpm).where(track_features.c.track_id.in_(ids))
        ).all()
    )
    if len(bpm) < 2:
        return picks
    rest = list(picks)
    out: list[tuple[int, Why]] = []
    prev = before
    if prev is None and rest:
        out.append(rest.pop(0))
        prev = out[0][0]
    while rest:
        window = rest[:_TEMPO_LOOKAHEAD]
        best = min(range(len(window)), key=lambda i: (_tempo_step(bpm.get(prev), bpm.get(window[i][0])), i))
        out.append(rest.pop(best))
        prev = out[-1][0]
    return out


def radio(
    conn: Connection,
    index: VectorIndex,
    track_id: int,
    n: int,
    rng: np.random.Generator,
    exclude: Collection[int] = (),
    user_id: int | None = None,
) -> Blend:
    """A station from one track: mostly close neighbours, a few further ones for variety, at most
    two tracks per album and never the same track twice. `exclude`: tracks the station already
    played (continuing it); then it does not start with the seed again."""
    skip = set(exclude)
    k = max(n * 4, 200) + len(skip)
    found = blend(conn, index, [track_id], k, user_id, f"track:{track_id}")
    why = dict(found.picks)
    candidates = [t for t, _ in found.picks if t not in skip]
    picked = _sample(conn, candidates, n if track_id in skip else n - 1, rng)
    out = [(t, why[t]) for t in picked]
    if track_id not in skip:
        out.insert(0, (track_id, {"seed": 1.0}))
    if sources.options(conn)["smooth_tempo"]:
        out = smooth_tempo(conn, out, None if track_id not in skip else _last(exclude))
    return Blend(out, found.via, found.skipped)


def _last(exclude: Collection[int]) -> int | None:
    """The track a continued station played last (the client sends them in play order)."""
    return list(exclude)[-1] if exclude else None


OWN_SHARE = 0.25  # of a group station: the album's/artist's own tracks, the rest is similar music


def group_radio(
    conn: Connection,
    index: VectorIndex,
    track_ids: list[int],
    n: int,
    rng: np.random.Generator,
    exclude: Collection[int] = (),
    user_id: int | None = None,
    station: str | None = None,
) -> Blend:
    """A station from an album or artist (`station`: "album:5" or "artist:2", see taste.py):
    tracks close to the group (by the switched-on sources),
    with about a quarter of the group's own tracks spread over it. Starts with one of the own
    tracks. `exclude`: tracks the station already played; once all own tracks were, they may
    come again."""
    skip = set(exclude)
    disliked = taste.dislikes(conn, user_id, station) if user_id is not None else set()
    wanted = [t for t in track_ids if t not in disliked]
    pool = [t for t in wanted if t not in skip] or wanted
    own = [(int(t), {"own": 1.0}) for t in rng.permutation(pool)[: max(1, round(n * OWN_SHARE))]]
    k = max(n * 4, 200) + len(skip)
    found = blend(conn, index, list(track_ids), k, user_id, station)
    why = dict(found.picks)
    picked = _sample(conn, [t for t, _ in found.picks if t not in skip], n - len(own), rng)
    others = [(t, why[t]) for t in picked]
    if not others:
        return Blend(own, skipped=found.skipped)
    # Own tracks at evenly spaced positions, the first one at the start.
    total = len(own) + len(others)
    own_at = {round(i * total / len(own)) for i in range(len(own))}
    own_it, others_it = iter(own), iter(others)
    out = [next(own_it) if i in own_at else next(others_it) for i in range(total)]
    if sources.options(conn)["smooth_tempo"]:
        out = smooth_tempo(conn, out, _last(exclude))
    return Blend(out, found.via, found.skipped)
