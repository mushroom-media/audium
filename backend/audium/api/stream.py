from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from audium.api.deps import current_user, get_db
from audium.db.engine import Database
from audium.errors import AudiumError
from audium.media.transcode import MAX_KBPS, MIN_KBPS, TARGETS
from audium.services import streaming
from audium.services.users import User

router = APIRouter(tags=["streaming"])


class TranscoderBusy(AudiumError):
    status = 503
    code = "transcoder_busy"

    def __init__(self) -> None:
        super().__init__("too many transcodes running, try again shortly")
        self.retry_after = 2


@router.get(
    "/tracks/{track_id}/stream",
    summary="Audio of a track",
    description=(
        "`format=raw` streams the original file with HTTP Range support (seeking via Range). "
        "`opus`/`aac`/`mp3` transcode on the fly with ffmpeg; seek by requesting again with `t` "
        "(start offset in seconds). The client picks the format from what its browser can play."
    ),
    response_class=StreamingResponse,
)
async def stream(
    track_id: int,
    request: Request,
    format: Literal["raw", "opus", "aac", "mp3"] = "raw",
    bitrate: int | None = Query(None, ge=MIN_KBPS, le=MAX_KBPS, description="kbit/s for transcoding"),
    t: float = Query(0, ge=0, le=86_400, description="Start offset in seconds (transcoding only)"),
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    def lookup():
        with db.read() as conn:
            return streaming.track_file(conn, track_id)

    tf = await run_in_threadpool(lookup)
    if format == "raw":
        return FileResponse(tf.path, media_type=tf.content_type, headers={"Cache-Control": "private, max-age=0"})

    transcoder = request.app.state.transcoder
    if transcoder.busy():
        raise TranscoderBusy()
    target = TARGETS[format]
    kbps = bitrate or target.default_kbps
    return StreamingResponse(
        transcoder.stream(tf.path, target, kbps, t),
        media_type=target.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Duration": f"{max(0.0, tf.duration_ms / 1000 - t):.3f}",
        },
    )
