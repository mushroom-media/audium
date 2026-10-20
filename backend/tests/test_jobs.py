import threading
import time

from sqlalchemy import select, update

from audium.db.schema import jobs
from audium.jobs import queue as q
from audium.jobs import worker as worker_module
from audium.jobs.worker import Worker


def _job(db, job_id):
    with db.read() as conn:
        return conn.execute(select(jobs).where(jobs.c.id == job_id)).one()


def test_dedupe_and_single_claim(db):
    with db.write() as conn:
        a = q.enqueue(conn, "scan", "scan", {"x": 1}, dedupe_key="k")
        b = q.enqueue(conn, "scan", "scan", {"x": 2}, dedupe_key="k")
        c = q.enqueue(conn, "scan", "other")
    assert a == b != c
    with db.write() as conn:
        first = q.claim(conn, "scan", "w1")
        second = q.claim(conn, "scan", "w2")
        third = q.claim(conn, "scan", "w3")
    assert {first.id, second.id} == {a, c}
    assert third is None
    assert first.payload == {"x": 1}


def test_priority_and_run_after(db):
    with db.write() as conn:
        low = q.enqueue(conn, "scan", "t", priority=0)
        high = q.enqueue(conn, "scan", "t", priority=5)
        later = q.enqueue(conn, "scan", "t", priority=9, delay_ms=60_000)
    with db.write() as conn:
        order = [q.claim(conn, "scan", "w").id, q.claim(conn, "scan", "w").id]
        assert q.claim(conn, "scan", "w") is None
    assert order == [high, low]
    assert _job(db, later).status == "queued"


def test_worker_runs_handler_and_stores_result(db):
    seen = []

    def handler(ctx, payload):
        ctx.progress(5, 10, "halfway")
        seen.append(payload)
        return {"ok": 1}

    w = Worker(db, "scan", {"t": handler})
    with db.write() as conn:
        job_id = q.enqueue(conn, "scan", "t", {"a": 1})
    assert w.run_one() is True
    assert w.run_one() is False
    row = _job(db, job_id)
    assert (row.status, row.progress, row.total, row.message) == ("done", 5, 10, "halfway")
    assert row.result_json == '{"ok": 1}'
    assert seen == [{"a": 1}]


def test_failures_retry_then_fail(db):
    def boom(ctx, payload):
        raise ValueError("bad file")

    w = Worker(db, "scan", {"t": boom})
    with db.write() as conn:
        job_id = q.enqueue(conn, "scan", "t", max_attempts=2)
    w.run_one()
    row = _job(db, job_id)
    assert row.status == "queued" and "bad file" in row.error and row.run_after > row.created_at
    with db.write() as conn:
        conn.execute(update(jobs).values(run_after=0))
    w.run_one()
    row = _job(db, job_id)
    assert row.status == "failed" and row.attempts == 2


def test_unknown_job_type_fails(db):
    with db.write() as conn:
        job_id = q.enqueue(conn, "scan", "mystery")
    Worker(db, "scan", {}).run_one()
    assert _job(db, job_id).status == "failed"


def test_cancel_running_job_via_heartbeat(db, monkeypatch):
    monkeypatch.setattr(worker_module, "HEARTBEAT_INTERVAL_S", 0.05)
    started = threading.Event()

    def long_job(ctx, payload):
        started.set()
        for _ in range(200):
            time.sleep(0.02)
            ctx.check()
        return {"finished": True}

    w = Worker(db, "scan", {"t": long_job})
    with db.write() as conn:
        job_id = q.enqueue(conn, "scan", "t")
    t = threading.Thread(target=w.run_one)
    t.start()
    assert started.wait(2)
    with db.write() as conn:
        assert q.request_cancel(conn, job_id) == "cancelling"
    t.join(5)
    assert _job(db, job_id).status == "cancelled"


def test_shutdown_requeues_without_burning_an_attempt(db):
    def job(ctx, payload):
        ctx.check()

    w = Worker(db, "scan", {"t": job})
    w.stop_event.set()
    with db.write() as conn:
        job_id = q.enqueue(conn, "scan", "t")
    w.run_one()
    row = _job(db, job_id)
    assert (row.status, row.attempts) == ("queued", 0)


def test_stale_jobs_are_reaped_and_reset(db):
    with db.write() as conn:
        a = q.enqueue(conn, "scan", "t")
        q.claim(conn, "scan", "dead-worker")
        conn.execute(update(jobs).where(jobs.c.id == a).values(heartbeat_at=0))
        assert q.reap_stale(conn, "analysis", 60_000) == 0  # other queues are not touched
        assert q.reap_stale(conn, "scan", 60_000) == 1
    assert _job(db, a).status == "queued"
    with db.write() as conn:
        q.claim(conn, "scan", "w")
        assert q.reset_running(conn) == 1
    assert _job(db, a).status == "queued"


def test_cancel_queued_job(db):
    with db.write() as conn:
        job_id = q.enqueue(conn, "scan", "t")
        assert q.request_cancel(conn, job_id) == "cancelled"
        assert q.claim(conn, "scan", "w") is None
