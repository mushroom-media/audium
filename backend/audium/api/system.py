import shutil

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from audium import __version__
from audium.api.deps import get_db
from audium.db.engine import Database
from audium.db.state import get_state
from audium.jobs.queue import QUEUES, worker_heartbeat_key
from audium.util import now_ms

router = APIRouter(tags=["system"])

_WORKER_STALE_MS = 60_000


@router.get("/health", summary="Liveness/readiness for Docker and monitoring (no auth)")
def health(db: Database = Depends(get_db)):
    body: dict = {"status": "ok", "version": __version__, "ffmpeg": shutil.which("ffmpeg") is not None}
    try:
        with db.read() as conn:
            conn.execute(text("SELECT 1"))
            workers = {}
            for q in QUEUES:
                beat = get_state(conn, worker_heartbeat_key(q))
                if beat is None:
                    workers[q] = "down"
                else:
                    workers[q] = "ok" if int(beat) + _WORKER_STALE_MS > now_ms() else "stale"
        body["db"] = "ok"
        body["workers"] = workers
    except Exception as exc:  # noqa: BLE001 - health must answer, whatever broke
        body.update(status="error", db=f"error: {type(exc).__name__}")
        return JSONResponse(body, status_code=503)
    body["analysis"] = "none"
    return body
