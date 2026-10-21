"""DB-backed job queue.

Workers claim jobs with a single UPDATE .. RETURNING inside a write transaction, so two workers
can never get the same job. (PostgreSQL would use SELECT .. FOR UPDATE SKIP LOCKED instead.)
Running jobs send heartbeats; a job whose worker stopped sending them is handed out again.
"""

import json
from dataclasses import dataclass

from sqlalchemy import Connection, func, select, update

from audium.db.schema import jobs
from audium.util import now_ms

QUEUES = ("scan", "analysis")
ACTIVE = ("queued", "running")
FINISHED = ("done", "failed", "cancelled")


def worker_heartbeat_key(queue: str) -> str:
    return f"worker.{queue}.heartbeat"


@dataclass(frozen=True)
class Job:
    id: int
    queue: str
    type: str
    payload: dict
    attempts: int
    max_attempts: int


def _job(row) -> Job:
    return Job(
        id=row.id,
        queue=row.queue,
        type=row.type,
        payload=json.loads(row.payload_json or "{}"),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
    )


def enqueue(
    conn: Connection,
    queue: str,
    type_: str,
    payload: dict | None = None,
    *,
    priority: int = 0,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
    delay_ms: int = 0,
) -> int:
    """Add a job. With `dedupe_key`, an already queued or running job with that key is reused."""
    if dedupe_key:
        existing = conn.execute(
            select(jobs.c.id).where(jobs.c.dedupe_key == dedupe_key, jobs.c.status.in_(ACTIVE)).limit(1)
        ).scalar()
        if existing is not None:
            return existing
    now = now_ms()
    return conn.execute(
        jobs.insert().values(
            queue=queue,
            type=type_,
            payload_json=json.dumps(payload or {}),
            dedupe_key=dedupe_key,
            priority=priority,
            status="queued",
            max_attempts=max_attempts,
            run_after=now + delay_ms,
            created_at=now,
        )
    ).inserted_primary_key[0]


def claim(conn: Connection, queue: str, worker_id: str) -> Job | None:
    now = now_ms()
    next_id = (
        select(jobs.c.id)
        .where(jobs.c.queue == queue, jobs.c.status == "queued", jobs.c.run_after <= now)
        .order_by(jobs.c.priority.desc(), jobs.c.id)
        .limit(1)
        .scalar_subquery()
    )
    row = conn.execute(
        update(jobs)
        .where(jobs.c.id == next_id, jobs.c.status == "queued")
        .values(
            status="running",
            worker_id=worker_id,
            started_at=now,
            heartbeat_at=now,
            attempts=jobs.c.attempts + 1,
        )
        .returning(jobs)
    ).first()
    return _job(row) if row else None


def heartbeat(conn: Connection, job_id: int, progress: int, total: int, message: str | None) -> bool:
    """Store progress; returns True when cancellation was requested."""
    conn.execute(
        update(jobs)
        .where(jobs.c.id == job_id)
        .values(progress=progress, total=total, message=message, heartbeat_at=now_ms())
    )
    return bool(conn.execute(select(jobs.c.cancel_requested).where(jobs.c.id == job_id)).scalar())


def finish(conn: Connection, job_id: int, status: str, result: dict | None = None, error: str | None = None):
    assert status in FINISHED
    conn.execute(
        update(jobs)
        .where(jobs.c.id == job_id)
        .values(
            status=status,
            result_json=json.dumps(result) if result is not None else None,
            error=error,
            finished_at=now_ms(),
            worker_id=None,
        )
    )


def requeue(
    conn: Connection, job_id: int, *, delay_ms: int = 0, error: str | None = None, count_attempt: bool = True
) -> None:
    values = {"status": "queued", "worker_id": None, "run_after": now_ms() + delay_ms}
    if error is not None:
        values["error"] = error
    if not count_attempt:
        values["attempts"] = jobs.c.attempts - 1
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(**values))


def request_cancel(conn: Connection, job_id: int) -> str | None:
    """Cancel a job. Queued jobs stop at once, running ones at their next checkpoint."""
    status = conn.execute(select(jobs.c.status).where(jobs.c.id == job_id)).scalar()
    if status == "queued":
        finish(conn, job_id, "cancelled")
        return "cancelled"
    if status == "running":
        conn.execute(update(jobs).where(jobs.c.id == job_id).values(cancel_requested=True))
        return "cancelling"
    return status


def reap_stale(conn: Connection, queue: str, stale_after_ms: int) -> int:
    """Hand out jobs of `queue` again whose worker stopped sending heartbeats (crash, OOM kill).
    Only a queue's own worker reaps it, so a slow scan is never stolen by another worker."""
    cutoff = now_ms() - stale_after_ms
    stale = conn.execute(
        select(jobs.c.id, jobs.c.attempts, jobs.c.max_attempts).where(
            jobs.c.queue == queue, jobs.c.status == "running", jobs.c.heartbeat_at < cutoff
        )
    ).all()
    for row in stale:
        if row.attempts >= row.max_attempts:
            finish(conn, row.id, "failed", error="worker stopped responding")
        else:
            requeue(conn, row.id, error="worker stopped responding")
    return len(stale)


def reset_running(conn: Connection) -> int:
    """At container start no worker is alive yet, so every running job is resumable."""
    res = conn.execute(update(jobs).where(jobs.c.status == "running").values(status="queued", worker_id=None))
    return res.rowcount


def prune_finished(conn: Connection, older_than_ms: int) -> None:
    cutoff = now_ms() - older_than_ms
    conn.execute(jobs.delete().where(jobs.c.status.in_(FINISHED), jobs.c.finished_at < cutoff))


def has_active(conn: Connection, queue: str, type_: str | None = None) -> bool:
    q = select(func.count()).select_from(jobs).where(jobs.c.queue == queue, jobs.c.status.in_(ACTIVE))
    if type_:
        q = q.where(jobs.c.type == type_)
    return conn.execute(q).scalar_one() > 0
