"""Jobs of the analysis worker (queue "analysis", runs at nice 19):

- genres:        one-time backfill of normalized genres for tracks scanned before phase 4
- analyze:       audio features for every track without (current) features, plus fingerprint and
                 styles where the EffNet models are available; resumable, because the state lives
                 per track in track_features / track_embeddings
- autoplaylists: derive detected genres from styles, regenerate auto-playlist suggestions and
                 smart playlists
"""

import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime

from sqlalchemy import Connection, Text, cast, func, literal, or_, select

from audium.analysis import autoplaylists, features, styles
from audium.analysis import genres as genre_norm
from audium.analysis import models as model_files
from audium.analysis.similarity import ANALYSIS_GENERATION
from audium.config import Settings
from audium.db.dialect import insert_for
from audium.db.engine import Database
from audium.db.schema import genres, library_roots, track_embeddings, track_features, track_genres, track_styles, tracks
from audium.db.state import RESET_STATE, bump_library_generation, get_state, set_state
from audium.i18n import server_language, tr
from audium.jobs import queue as jobq
from audium.jobs.worker import JobContext
from audium.logging import get_logger
from audium.scanner.covers import CoverStore
from audium.scanner.scan import genre_id, refresh_genre_counts
from audium.services import auth as auth_service
from audium.services.server_settings import server_setting
from audium.util import now_ms

log = get_logger(__name__)

ANALYSIS_QUEUE = "analysis"
BACKEND_STATE = "analysis.backend"
GENRES_DONE_STATE = "genres.backfilled"
# Why a stopped analysis waits ("paused" / "window"); empty when it is not waiting.
WAITING_STATE = "analysis.waiting"
# Tracks per batch and process: settings (pause, window, processes) apply between batches.
_BATCH_PER_WORKER = 4
_RESUME_CHECK_S = 60
_GENRE_BATCH = 2000


def enqueue_analysis(conn: Connection) -> None:
    jobq.enqueue(conn, ANALYSIS_QUEUE, "analyze", dedupe_key="analysis:analyze", priority=0)


def enqueue_autoplaylists(conn: Connection) -> int:
    return jobq.enqueue(conn, ANALYSIS_QUEUE, "autoplaylists", dedupe_key="analysis:autoplaylists", priority=5)


def _fingerprint_sql():
    return cast(tracks.c.size, Text) + literal(":") + cast(tracks.c.mtime_ns, Text) + literal(":") + tracks.c.quick_hash


def _effnet_on(conn: Connection) -> bool:
    """The analysis runs the EffNet models (decided at the start of each analysis job)."""
    return "+effnet" in (get_state(conn, BACKEND_STATE) or "")


def _pending_condition(effnet: bool):
    f, e = track_features, track_embeddings
    stale = [
        f.c.track_id.is_(None),
        f.c.fingerprint != _fingerprint_sql(),  # file changed since the last analysis
        (f.c.status == "ok") & (f.c.analyzer_version < features.ANALYZER_VERSION),
    ]
    if effnet:  # analysed before the models were there (or with an older model)
        stale.append((f.c.status == "ok") & (e.c.model.is_(None) | (e.c.model != features.EMBEDDING_MODEL)))
    return (tracks.c.missing_since.is_(None)) & (library_roots.c.enabled.is_(True)) & or_(*stale)


def _pending_base():
    return (
        tracks.join(library_roots, library_roots.c.id == tracks.c.root_id)
        .outerjoin(track_features, track_features.c.track_id == tracks.c.id)
        .outerjoin(track_embeddings, track_embeddings.c.track_id == tracks.c.id)
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
    pending = select(func.count()).select_from(_pending_base()).where(_pending_condition(_effnet_on(conn)))
    fingerprints = (
        select(func.count())
        .select_from(track_embeddings.join(tracks, tracks.c.id == track_embeddings.c.track_id))
        .where(
            track_embeddings.c.model == features.EMBEDDING_MODEL,
            track_embeddings.c.vector.is_not(None),
            tracks.c.missing_since.is_(None),
        )
    )
    with_styles = (
        select(func.count(func.distinct(track_styles.c.track_id)))
        .select_from(track_styles.join(tracks, tracks.c.id == track_styles.c.track_id))
        .where(tracks.c.missing_since.is_(None))
    )
    return {
        "waiting": analysis_blocked(conn),
        "cpus": os.cpu_count() or 1,
        "server_time": datetime.now().strftime("%H:%M"),
        "fingerprints": conn.execute(fingerprints).scalar_one(),
        "styles": conn.execute(with_styles).scalar_one(),
        "backend": get_state(conn, BACKEND_STATE) or "unknown",
        "tracks": conn.execute(present).scalar_one(),
        "analyzed": conn.execute(ok).scalar_one(),
        "failed": conn.execute(failed).scalar_one(),
        "pending": conn.execute(pending).scalar_one(),
    }


def analysis_workers(conn: Connection, settings: Settings) -> int:
    """Parallel analysis processes: the admin's setting, else AUDIUM_ANALYSIS_WORKERS."""
    value = server_setting(conn, "analysis_workers")
    return max(1, settings.analysis_workers if value == "default" else int(value))


def analysis_blocked(conn: Connection, now: datetime | None = None) -> str | None:
    """Why the analysis must not run now: "paused", "window" (outside the time window, server
    time), or None."""
    if server_setting(conn, "analysis_paused") == "on":
        return "paused"
    if server_setting(conn, "analysis_schedule") == "window":
        start, end = int(server_setting(conn, "analysis_from")), int(server_setting(conn, "analysis_until"))
        hour = (now or datetime.now()).hour
        inside = start <= hour < end if start <= end else hour >= start or hour < end
        if start != end and not inside:
            return "window"
    return None


def _next_batch(conn: Connection, size: int, skip: set[int], effnet: bool):
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
        .where(_pending_condition(effnet))
        .order_by(tracks.c.id)
        .limit(size + len(skip))
    )
    return [r for r in conn.execute(q) if r.id not in skip][:size]


def _store(conn: Connection, results: list[tuple], analyzer: str, style_cache: dict[str, int]) -> tuple[int, int]:
    ok = failed = 0
    ts = now_ms()
    for track_id, fp, feats, error in results:
        feats = dict(feats) if feats else None
        model = feats.pop("embedding_model", None) if feats else None
        vector = feats.pop("embedding", None) if feats else None
        found = feats.pop("styles", []) if feats else []
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
        if model:
            _store_effnet(conn, track_id, model, vector, found, style_cache)
        if feats:
            ok += 1
        else:
            failed += 1
    return ok, failed


def _store_effnet(conn: Connection, track_id: int, model: str, vector, found: list, style_cache: dict[str, int]):
    emb = {"model": model, "vector": vector}
    stmt = insert_for(conn, track_embeddings).values(track_id=track_id, **emb)
    conn.execute(stmt.on_conflict_do_update(index_elements=[track_embeddings.c.track_id], set_=emb))
    conn.execute(track_styles.delete().where(track_styles.c.track_id == track_id))
    if found:
        ids = styles.style_ids(conn, {label for label, _p in found}, style_cache)
        conn.execute(
            track_styles.insert(),
            [{"track_id": track_id, "style_id": ids[label], "prob": prob} for label, prob in found],
        )


def run_analysis(ctx: JobContext, db: Database, settings: Settings) -> dict:
    models_dir = settings.data_dir / "models"
    with db.read() as conn:
        lang = server_language(conn)  # of the progress messages
        # Not while paused or outside the time window: then the analysis would not run anyway.
        download = (
            settings.analysis_download_models
            and server_setting(conn, "model_download") == "on"
            and analysis_blocked(conn) is None
        )
    if features.effnet_available() and not model_files.present(models_dir) and download:
        ctx.progress(0, 0, tr(lang, "Modelle werden geladen"))
        model_files.ensure(models_dir, download=True)
    analyzer = features.backend_name(models_dir)
    effnet = "+effnet" in analyzer
    with db.write() as conn:
        set_state(conn, BACKEND_STATE, analyzer)
    if analyzer == "none":
        return {"skipped": "Essentia is not available on this platform"}
    with db.read() as conn:
        pending = select(func.count()).select_from(_pending_base()).where(_pending_condition(effnet))
        total = conn.execute(pending).scalar_one()
        workers = analysis_workers(conn, settings)
    done = ok = failed = 0
    waiting: str | None = None
    attempted: set[int] = set()
    style_cache: dict[str, int] = {}
    ctx.progress(0, total, tr(lang, "Analyse startet"))

    def new_pool():
        return ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("forkserver"), initializer=features.init_worker
        )

    pool = new_pool()
    try:
        while not ctx.should_stop():
            with db.read() as conn:
                # The admin may pause, set a time window or change the processes at any time.
                waiting = analysis_blocked(conn)
                wanted = analysis_workers(conn, settings)
                batch = [] if waiting else _next_batch(conn, wanted * _BATCH_PER_WORKER, attempted, effnet)
            if waiting:
                ctx.progress(
                    done, max(total, done), "Pausiert" if waiting == "paused" else "Wartet auf das Zeitfenster"
                )
                break
            if not batch:
                break
            if wanted != workers:
                pool.shutdown()
                workers = wanted
                pool = new_pool()
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
                n_ok, n_failed = _store(conn, results, analyzer, style_cache)
                set_state(conn, ANALYSIS_GENERATION, str(now_ms()))
            ok += n_ok
            failed += n_failed
            done += len(results)
            last = batch[-1].rel_path
            ctx.progress(
                done,
                max(total, done),
                tr(lang, "{done} von {total} analysiert · {last}", done=done, total=max(total, done), last=last),
            )
    finally:
        pool.shutdown(cancel_futures=True)
    ctx.check()
    with db.write() as conn:
        set_state(conn, WAITING_STATE, waiting or "")  # the scheduler resumes it once allowed
        if ok:
            enqueue_autoplaylists(conn)
    return {"analyzed": ok, "failed": failed, **({"waiting": waiting} if waiting else {})}


def run_genre_backfill(ctx: JobContext, db: Database) -> dict:
    """Normalized genres for tracks that were scanned before genres existed (or changed rules)."""
    cache: dict[str, int] = {}
    with db.read() as conn:
        lang = server_language(conn)
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
        ctx.progress(done, total, tr(lang, "Genres werden vereinheitlicht"))
        ctx.check()
    with db.write() as conn:
        refresh_genre_counts(conn)
        set_state(conn, GENRES_DONE_STATE, "1")
        bump_library_generation(conn)
        enqueue_autoplaylists(conn)
    return {"tracks": done, "genres": _count(db, genres)}


def refresh_detected_genres(conn: Connection) -> None:
    """Genres from the detected styles for tracks without genre tags (see analysis/styles.py)."""
    has_styles = conn.execute(select(track_styles.c.track_id).limit(1)).first() is not None
    has_detected = conn.execute(
        select(track_genres.c.track_id).where(track_genres.c.source == "detected").limit(1)
    ).first()
    if not has_styles and has_detected is None:
        return
    cache: dict[str, int] = {}
    n = styles.refresh_detected_genres(conn, lambda name: genre_id(conn, cache, name))
    styles.refresh_style_counts(conn)
    refresh_genre_counts(conn)
    bump_library_generation(conn)
    log.info("genres.detected", tracks=n)


def _count(db: Database, table) -> int:
    with db.read() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def make_handlers(db: Database, settings: Settings):
    def analyze(ctx: JobContext, payload: dict) -> dict:
        return run_analysis(ctx, db, settings)

    def regenerate(ctx: JobContext, payload: dict) -> dict:
        with db.write() as conn:
            ctx.progress(0, 1, tr(server_language(conn), "Auto-Playlists werden erzeugt"))
            refresh_detected_genres(conn)
        return autoplaylists.generate_in(db, CoverStore(settings.covers_dir))

    def backfill(ctx: JobContext, payload: dict) -> dict:
        return run_genre_backfill(ctx, db)

    return {"analyze": analyze, "autoplaylists": regenerate, "genres": backfill}


class AnalysisScheduler:
    """Idle ticks of the analysis worker. The first one backfills genres once and resumes
    pending analysis; later ones (once a minute) resume an analysis that stopped for the pause
    or the time window as soon as it may run again."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._started = False
        self._last_check = 0.0
        self._reset_at: str | None = None

    def __call__(self) -> None:
        if self._started:
            self._resume_if_allowed()
            return
        with self.db.read() as conn:
            self._reset_at = get_state(conn, RESET_STATE)
            if auth_service.setup_holds_scan(conn, self.settings):
                return  # the first-run dialog decides about the analysis and its model download
        self._started = True
        self._last_check = time.monotonic()
        analyzer = features.backend_name(self.settings.data_dir / "models")
        with self.db.write() as conn:
            set_state(conn, BACKEND_STATE, analyzer)
            if not get_state(conn, GENRES_DONE_STATE):
                jobq.enqueue(conn, ANALYSIS_QUEUE, "genres", dedupe_key="analysis:genres", priority=10)
            if analyzer != "none" and self.settings.analysis_enabled:
                enqueue_analysis(conn)
            enqueue_autoplaylists(conn)
        log.info("analysis.backend", backend=analyzer)

    def _resume_if_allowed(self) -> None:
        if time.monotonic() - self._last_check < _RESUME_CHECK_S or not self.settings.analysis_enabled:
            return
        self._last_check = time.monotonic()
        with self.db.write() as conn:
            if get_state(conn, RESET_STATE) != self._reset_at:
                self._started = False  # reset to factory settings: wait for the dialog again
                return
            if get_state(conn, WAITING_STATE) and analysis_blocked(conn) is None:
                set_state(conn, WAITING_STATE, "")
                enqueue_analysis(conn)
                log.info("analysis.resumed")
