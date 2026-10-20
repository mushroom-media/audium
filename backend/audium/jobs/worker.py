"""Worker loop: claims jobs from one queue and runs their handlers."""

import os
import signal
import socket
import threading
import time
import traceback
from collections.abc import Callable

from audium.db.engine import Database
from audium.db.state import set_state
from audium.jobs import queue as q
from audium.logging import get_logger
from audium.util import now_ms

log = get_logger(__name__)

HEARTBEAT_INTERVAL_S = 2.0
STALE_AFTER_MS = 60_000
_WORKER_BEAT_S = 10.0
_REAP_EVERY_S = 30.0
_RETRY_BASE_MS = 30_000


class JobCancelled(Exception):
    pass


class WorkerShutdown(Exception):
    pass


class JobContext:
    """Handed to job handlers: progress reporting and cooperative cancellation."""

    def __init__(self, job: q.Job, stop_event: threading.Event) -> None:
        self.job = job
        self._stop = stop_event
        self._cancel = False
        self._lock = threading.Lock()
        self.done = 0
        self.total = 0
        self.message: str | None = None

    def progress(self, done: int, total: int | None = None, message: str | None = None) -> None:
        with self._lock:
            self.done = done
            if total is not None:
                self.total = total
            if message is not None:
                self.message = message[:300]

    def snapshot(self) -> tuple[int, int, str | None]:
        with self._lock:
            return self.done, self.total, self.message

    def mark_cancelled(self) -> None:
        self._cancel = True

    def should_stop(self) -> bool:
        return self._cancel or self._stop.is_set()

    def check(self) -> None:
        """Raise if the job should end now. Call at safe points (after a batch is committed)."""
        if self._cancel:
            raise JobCancelled()
        if self._stop.is_set():
            raise WorkerShutdown()


Handler = Callable[[JobContext, dict], dict | None]


class Worker:
    def __init__(
        self,
        db: Database,
        queue: str,
        handlers: dict[str, Handler],
        *,
        on_idle: Callable[[], None] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.db = db
        self.queue = queue
        self.handlers = handlers
        self.on_idle = on_idle
        self.poll_interval = poll_interval
        self.stop_event = threading.Event()
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{queue}"

    def install_signal_handlers(self) -> None:
        def _stop(signum, _frame):
            log.info("worker.stopping", signal=signum)
            self.stop_event.set()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

    def run_forever(self) -> None:
        log.info("worker.started", queue=self.queue, worker_id=self.worker_id)
        last_beat = last_reap = 0.0
        while not self.stop_event.is_set():
            mono = time.monotonic()
            if mono - last_beat >= _WORKER_BEAT_S:
                with self.db.write() as conn:
                    set_state(conn, q.worker_heartbeat_key(self.queue), str(now_ms()))
                last_beat = mono
            if mono - last_reap >= _REAP_EVERY_S:
                with self.db.write() as conn:
                    if n := q.reap_stale(conn, self.queue, STALE_AFTER_MS):
                        log.warning("jobs.reaped", count=n)
                last_reap = mono
            if not self.run_one():
                if self.on_idle:
                    try:
                        self.on_idle()
                    except Exception:
                        log.exception("worker.on_idle_failed")
                self.stop_event.wait(self.poll_interval)
        log.info("worker.stopped", queue=self.queue)

    def run_one(self) -> bool:
        """Claim and run one job. Returns False if the queue was empty."""
        with self.db.write() as conn:
            job = q.claim(conn, self.queue, self.worker_id)
        if job is None:
            return False
        self._execute(job)
        return True

    def _execute(self, job: q.Job) -> None:
        handler = self.handlers.get(job.type)
        if handler is None:
            with self.db.write() as conn:
                q.finish(conn, job.id, "failed", error=f"unknown job type {job.type!r}")
            return
        ctx = JobContext(job, self.stop_event)
        beat_stop = threading.Event()
        beat = threading.Thread(target=self._heartbeat_loop, args=(ctx, beat_stop), daemon=True)
        beat.start()
        log.info("job.started", job_id=job.id, type=job.type, attempt=job.attempts)
        try:
            result = handler(ctx, job.payload)
            outcome = ("done", result, None)
        except JobCancelled:
            outcome = ("cancelled", None, None)
        except WorkerShutdown:
            outcome = ("requeue", None, None)
        except Exception as exc:
            log.exception("job.failed", job_id=job.id, type=job.type)
            outcome = ("error", None, "".join(traceback.format_exception_only(exc)).strip()[:2000])
        finally:
            beat_stop.set()
            beat.join()

        status, result, error = outcome
        with self.db.write() as conn:
            done, total, message = ctx.snapshot()
            q.heartbeat(conn, job.id, done, total, message)
            if status == "requeue":
                # Interrupted by shutdown: resume on next start, without burning an attempt.
                q.requeue(conn, job.id, count_attempt=False)
            elif status == "error":
                if job.attempts < job.max_attempts:
                    q.requeue(conn, job.id, delay_ms=_RETRY_BASE_MS * 2 ** (job.attempts - 1), error=error)
                else:
                    q.finish(conn, job.id, "failed", error=error)
            else:
                q.finish(conn, job.id, status, result=result)
        log.info("job.finished", job_id=job.id, type=job.type, status=status)

    def _heartbeat_loop(self, ctx: JobContext, stop: threading.Event) -> None:
        while not stop.wait(HEARTBEAT_INTERVAL_S):
            try:
                done, total, message = ctx.snapshot()
                with self.db.write() as conn:
                    if q.heartbeat(conn, ctx.job.id, done, total, message):
                        ctx.mark_cancelled()
            except Exception:
                log.exception("job.heartbeat_failed", job_id=ctx.job.id)
