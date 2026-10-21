"""Jobs of the analysis worker (queue "analysis", runs at nice 19):

- genres:        one-time backfill of normalized genres for tracks scanned before phase 4
- analyze:       audio features for every track without (current) features; resumable, because
                 the state lives per track in track_features
- autoplaylists: regenerate auto-playlist suggestions and smart playlists
"""

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from sqlalchemy import Connection, Text, cast, func, literal, or_, select

from audium.analysis import autoplaylists, features
from audium.analysis import genres as genre_norm
from audium.analysis.similarity import ANALYSIS_GENERATION
from audium.config import Settings
from audium.db.dialect import insert_for
from audium.db.engine import Database
from audium.db.schema import genres, library_roots, track_features, track_genres, tracks
from audium.db.state import bump_library_generation, get_state, set_state
from audium.jobs import queue as jobq
from audium.jobs.worker import JobContext
from audium.logging import get_logger
from audium.scanner.scan import genre_id, refresh_genre_counts
from audium.util import now_ms

log = get_logger(__name__)

ANALYSIS_QUEUE = "analysis"
BACKEND_STATE = "analysis.backend"
GENRES_DONE_STATE = "genres.backfilled"
_BATCH = 24
_GENRE_BATCH = 2000


def enqueue_analysis(conn: Connection) -> None:
    jobq.enqueue(conn, ANALYSIS_QUEUE, "analyze", dedupe_key="analysis:analyze", priority=0)


def enqueue_autoplaylists(conn: Connection) -> int:
    return jobq.enqueue(conn, ANALYSIS_QUEUE, "autoplaylists", dedupe_key="analysis:autoplaylists", priority=5)


def _fingerprint_sql():
    return cast(tracks.c.size, Text) + literal(":") + cast(tracks.c.mtime_ns, Text) + literal(":") + tracks.c.quick_hash


def _pending_condition():
    f = track_features
    return (
        (tracks.c.missing_since.is_(None))
        & (library_roots.c.enabled.is_(True))
        & or_(
            f.c.track_id.is_(None),
            f.c.fingerprint != _fingerprint_sql(),  # file changed since the last analysis
            (f.c.status == "ok") & (f.c.analyzer_version < features.ANALYZER_VERSION),
        )
    )


def _pending_base():
    return tracks.join(library_roots, library_roots.c.id == tracks.c.root_id).outerjoin(
        track_features, track_features.c.track_id == tracks.c.id
    )


def analysis_stats(conn: Connection) -> dict:
    f = track_features
    present = select(func.count()).select_from(tracks).where(tracks.c.missing_since.is_(None))
    ok = (
        select(func.count())
        .select_from(f.join(tracks, tracks.c.id == f.c.track_id))
        .where(f.c.status == "ok", tracks.c.missing_since.is_(None))
    )
    failed = (
        select(func.count())
        .select_from(f.join(tracks, tracks.c.id == f.c.track_id))
        .where(f.c.status == "failed", tracks.c.missing_since.is_(None))
    )
    pending = select(func.count()).select_from(_pending_base()).where(_pending_condition())
    return {
        "backend": get_state(conn, BACKEND_STATE) or "unknown",
        "tracks": conn.execute(present).scalar_one(),
        "analyzed": conn.execute(ok).scalar_one(),
        "failed": conn.execute(failed).scalar_one(),
        "pending": conn.execute(pending).scalar_one(),
    }


def _next_batch(conn: Connection, size: int, skip: set[int]):
    q = (
        select(
            tracks.c.id,
            tracks.c.rel_path,
            tracks.c.duration_ms,
            tracks.c.size,
            tracks.c.mtime_ns,
            tracks.c.quick_hash,
            library_roots.c.path.label("root"),
        )
        .select_from(_pending_base())
        .where(_pending_condition())
        .order_by(tracks.c.id)
        .limit(size + len(skip))
    )
    return [r for r in conn.execute(q) if r.id not in skip][:size]


def _store(conn: Connection, results: list[tuple], analyzer: str) -> tuple[int, int]:
    ok = failed = 0
    ts = now_ms()
    for track_id, fp, feats, error in results:
        values = {
            "analyzer": analyzer,
            "analyzer_version": features.ANALYZER_VERSION,
            "status": "ok" if feats else "failed",
            "error": error,
            "fingerprint": fp,
            "analyzed_at": ts,
            **{k: None for k in ("bpm", "key", "mode", "loudness", "energy", "dynamics", "danceability",
                                 "brightness", "mood_happy", "mood_sad", "mood_aggressive", "mood_relaxed")},
            **(feats or {}),
        }  # fmt: skip
        stmt = insert_for(conn, track_features).values(track_id=track_id, **values)
        conn.execute(stmt.on_conflict_do_update(index_elements=[track_features.c.track_id], set_=values))
        if feats:
            ok += 1
        else:
            failed += 1
    return ok, failed


def run_analysis(ctx: JobContext, db: Database, settings: Settings) -> dict:
    models_dir = settings.data_dir / "models"
    analyzer = features.backend_name(models_dir)
    with db.write() as conn:
        set_state(conn, BACKEND_STATE, analyzer)
    if analyzer == "none":
        return {"skipped": "Essentia is not available on this platform"}
    with db.read() as conn:
        total = conn.execute(select(func.count()).select_from(_pending_base()).where(_pending_condition())).scalar_one()
    done = ok = failed = 0
    attempted: set[int] = set()
    workers = max(1, settings.analysis_workers)
    ctx.progress(0, total, "Analyse startet")

    def new_pool():
        return ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("forkserver"))

    pool = new_pool()
    try:
        while not ctx.should_stop():
            with db.read() as conn:
                batch = _next_batch(conn, _BATCH, attempted)
            if not batch:
                break
            args = [
                (r.id, os.path.join(r.root, r.rel_path), r.duration_ms,
                 features.fingerprint(r.size, r.mtime_ns, r.quick_hash), str(models_dir))
                for r in batch
            ]  # fmt: skip
            attempted.update(r.id for r in batch)
            try:
                results = list(pool.map(features.analyze_one, args))
            except BrokenProcessPool:
                # A file crashed the analyzer (native code). Find it by retrying one at a time.
                pool.shutdown(cancel_futures=True)
                results = []
                for a in args:
                    pool = new_pool()
                    try:
                        results.append(pool.submit(features.analyze_one, a).result())
                    except BrokenProcessPool:
                        results.append((a[0], a[3], None, "analyzer crashed on this file"))
                        pool.shutdown(cancel_futures=True)
                pool = new_pool()
            with db.write() as conn:
                n_ok, n_failed = _store(conn, results, analyzer)
                set_state(conn, ANALYSIS_GENERATION, str(now_ms()))
            ok += n_ok
            failed += n_failed
            done += len(results)
            last = batch[-1].rel_path
            ctx.progress(done, max(total, done), f"{done} von {max(total, done)} analysiert · {last}")
    finally:
        pool.shutdown(cancel_futures=True)
    ctx.check()
    with db.write() as conn:
        if ok:
            enqueue_autoplaylists(conn)
    return {"analyzed": ok, "failed": failed}


def run_genre_backfill(ctx: JobContext, db: Database) -> dict:
    """Normalized genres for tracks that were scanned before genres existed (or changed rules)."""
    cache: dict[str, int] = {}
    with db.read() as conn:
        total = conn.execute(
            select(func.count()).select_from(tracks).where(tracks.c.genre_raw.is_not(None))
        ).scalar_one()
    last_id = done = 0
    while True:
        with db.write() as conn:
            rows = conn.execute(
                select(tracks.c.id, tracks.c.genre_raw)
                .where(tracks.c.id > last_id, tracks.c.genre_raw.is_not(None))
                .order_by(tracks.c.id)
                .limit(_GENRE_BATCH)
            ).all()
            if not rows:
                break
            ids = [r.id for r in rows]
            conn.execute(track_genres.delete().where(track_genres.c.track_id.in_(ids)))
            link = [
                {"track_id": r.id, "genre_id": genre_id(conn, cache, name)}
                for r in rows
                for name in genre_norm.normalize(r.genre_raw.split("; "))
            ]
            if link:
                conn.execute(track_genres.insert(), link)
            last_id = ids[-1]
        done += len(rows)
        ctx.progress(done, total, "Genres werden vereinheitlicht")
        ctx.check()
    with db.write() as conn:
        refresh_genre_counts(conn)
        set_state(conn, GENRES_DONE_STATE, "1")
        bump_library_generation(conn)
        enqueue_autoplaylists(conn)
    return {"tracks": done, "genres": _count(db, genres)}


def _count(db: Database, table) -> int:
    with db.read() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def make_handlers(db: Database, settings: Settings):
    def analyze(ctx: JobContext, payload: dict) -> dict:
        return run_analysis(ctx, db, settings)

    def regenerate(ctx: JobContext, payload: dict) -> dict:
        ctx.progress(0, 1, "Auto-Playlists werden erzeugt")
        with db.write() as conn:
            return autoplaylists.generate(conn)

    def backfill(ctx: JobContext, payload: dict) -> dict:
        return run_genre_backfill(ctx, db)

    return {"analyze": analyze, "autoplaylists": regenerate, "genres": backfill}


class AnalysisScheduler:
    """First idle tick of the analysis worker: backfill genres once, resume pending analysis."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._started = False

    def __call__(self) -> None:
        if self._started:
            return
        self._started = True
        analyzer = features.backend_name(self.settings.data_dir / "models")
        with self.db.write() as conn:
            set_state(conn, BACKEND_STATE, analyzer)
            if not get_state(conn, GENRES_DONE_STATE):
                jobq.enqueue(conn, ANALYSIS_QUEUE, "genres", dedupe_key="analysis:genres", priority=10)
            if analyzer != "none" and self.settings.analysis_enabled:
                enqueue_analysis(conn)
            enqueue_autoplaylists(conn)
        log.info("analysis.backend", backend=analyzer)
