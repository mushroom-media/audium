"""Job handlers and the periodic scheduler of the scan worker."""

import time

from audium.analysis import taste
from audium.auth import ratelimit
from audium.config import Settings
from audium.db.engine import Database
from audium.db.state import RESET_STATE, get_state, set_state
from audium.jobs import queue as jobq
from audium.jobs.worker import JobContext
from audium.logging import get_logger
from audium.scanner.covers import CoverStore
from audium.scanner.scan import Scanner
from audium.services import auth as auth_service
from audium.services import playlists as playlist_service
from audium.services import roots as root_service
from audium.services import similar_artists
from audium.util import now_ms

log = get_logger(__name__)

SCAN_QUEUE = "scan"
_LAST_AUTO_SCAN = "scan.last_auto"
_LAST_MAINTENANCE = "maintenance.last_run"
_TICK_S = 60.0
_DAY_MS = 86_400_000
_JOB_RETENTION_MS = 30 * _DAY_MS


def enqueue_scan(conn, root_ids: list[int] | None = None, force: bool = False) -> int:
    scope = f"roots:{','.join(map(str, sorted(root_ids)))}" if root_ids else "all"
    key = f"scan:{scope}:{int(force)}"
    return jobq.enqueue(
        conn, SCAN_QUEUE, "scan", {"root_ids": root_ids, "force": force}, dedupe_key=key, max_attempts=5
    )


def make_handlers(db: Database, settings: Settings):
    cover_store = CoverStore(settings.covers_dir)

    def scan(ctx: JobContext, payload: dict) -> dict:
        stats = Scanner(db, settings, cover_store, ctx).run(payload.get("root_ids"), bool(payload.get("force")))
        ctx.check()  # report a cancelled / interrupted scan as such
        if stats.added or stats.updated or stats.moved or stats.missing or stats.purged or stats.restored:
            # New or changed files: analyse them, then refresh the auto-playlists.
            from audium.analysis.tasks import enqueue_analysis, enqueue_autoplaylists

            with db.write() as conn:
                if settings.analysis_enabled:
                    enqueue_analysis(conn)
                enqueue_autoplaylists(conn)
        return stats.as_dict()

    def similar(ctx: JobContext, payload: dict) -> dict:
        # Small batches, each its own job, so a scan never waits long behind the requests.
        with db.read() as conn:
            if not similar_artists.enabled(conn):
                return {"artists": 0}
        ctx.progress(0, 1, "Ähnliche Künstler werden abgefragt")
        stats = similar_artists.run_batch(db)
        if stats["left"]:
            with db.write() as conn:
                if similar_artists.enabled(conn):
                    similar_artists.enqueue(conn, delay_ms=1000)
        return stats

    return {"scan": scan, similar_artists.JOB_TYPE: similar}


class ScanScheduler:
    """Runs when the scan worker is idle: first-start setup, periodic rescans, housekeeping."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._started = False
        self._held = False
        self._last_tick = 0.0
        self._reset_at: str | None = None

    def __call__(self) -> None:
        if not self._started:
            with self.db.read() as conn:
                self._reset_at = get_state(conn, RESET_STATE)
                if auth_service.setup_holds_scan(conn, self.settings):
                    self._held = True
                    return
            self._on_start()
            self._started = True
        mono = time.monotonic()
        if mono - self._last_tick < _TICK_S:
            return
        self._last_tick = mono
        with self.db.read() as conn:
            if get_state(conn, RESET_STATE) != self._reset_at:
                # Reset to factory settings: as after a first start, wait for the dialog.
                self._started = self._held = False
                return
        self._periodic()

    def _on_start(self) -> None:
        with self.db.write() as conn:
            added = root_service.discover_initial_roots(conn, self.settings)
            if added:
                log.info("library.roots_discovered", roots=added)
            # After the first-run dialog there is nothing to catch up on: it started the scan itself.
            scan = (self.settings.scan_on_start and not self._held) or added
            if scan:
                enqueue_scan(conn)
            if scan or self._held:
                set_state(conn, _LAST_AUTO_SCAN, str(now_ms()))

    def _periodic(self) -> None:
        now = now_ms()
        with self.db.write() as conn:
            interval = self.settings.scan_interval_minutes * 60_000
            if interval > 0:
                last = int(get_state(conn, _LAST_AUTO_SCAN) or 0)
                if now - last >= interval and not jobq.has_active(conn, SCAN_QUEUE, "scan"):
                    enqueue_scan(conn)
                    set_state(conn, _LAST_AUTO_SCAN, str(now))
            if (
                similar_artists.enabled(conn)
                and not jobq.has_active(conn, SCAN_QUEUE, similar_artists.JOB_TYPE)
                and similar_artists.pending(conn, 1)
            ):
                similar_artists.enqueue(conn)  # new artists, or answers due for a refresh
            last_maintenance = int(get_state(conn, _LAST_MAINTENANCE) or 0)
            if now - last_maintenance >= _DAY_MS:
                auth_service.prune_sessions(conn)
                ratelimit.prune(conn, now, self.settings.login_window_minutes * 60_000)
                jobq.prune_finished(conn, _JOB_RETENTION_MS)
                playlist_service.prune_events(conn)
                taste.prune_skips(conn)
                set_state(conn, _LAST_MAINTENANCE, str(now))
