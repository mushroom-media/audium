import importlib.util
import os
import platform
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response

from audium.api.deps import clear_session_cookie, client_ip, get_db, get_settings, require_admin
from audium.api.setup_models import ProbeIn, ProbeOut, ResetIn, ResetOut, SetupComplete, SetupCompleted, SetupInfo
from audium.config import Settings
from audium.db.engine import Database
from audium.services import auth as auth_service
from audium.services import reset as reset_service
from audium.services import setup as setup_service
from audium.services.nowplaying import NowPlaying
from audium.services.users import User

router = APIRouter(prefix="/admin/setup", tags=["admin: setup"])


def _analysis_available(settings: Settings) -> bool:
    # find_spec instead of importing: Essentia with TensorFlow costs hundreds of MB in the API.
    return (
        settings.analysis_enabled
        and platform.machine().lower() in ("x86_64", "amd64")
        and importlib.util.find_spec("essentia") is not None
    )


def _proxy_not_trusted(request: Request) -> bool:
    # uvicorn replaces the client address with the forwarded one only for a trusted proxy.
    forwarded = request.headers.get("x-forwarded-for")
    return bool(forwarded) and client_ip(request) not in {p.strip() for p in forwarded.split(",")}


@router.get("", response_model=SetupInfo, summary="What the first-run dialog needs to know")
def setup_info(
    request: Request,
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.read() as conn:
        info = setup_service.status(conn, settings)
    return SetupInfo(
        **info,
        analysis_available=_analysis_available(settings),
        cpus=os.cpu_count() or 1,
        https=request.url.scheme == "https",
        proxy_not_trusted=_proxy_not_trusted(request),
        utc_offset_minutes=int(datetime.now().astimezone().utcoffset().total_seconds() // 60),
    )


@router.post("/probe", response_model=ProbeOut, summary="Trial scan of a folder (writes nothing, stops at its limits)")
def probe(body: ProbeIn, _admin: User = Depends(require_admin), settings: Settings = Depends(get_settings)):
    return setup_service.probe(settings, body.path)


@router.post("/complete", response_model=SetupCompleted, summary="End the dialog and start the scan")
def complete(
    body: SetupComplete,
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        return SetupCompleted(job_id=setup_service.complete(conn, settings, body.roots))


@router.post("/reset", response_model=ResetOut, summary="Reset to factory settings; the first-run dialog opens again")
def reset(
    body: ResetIn,
    request: Request,
    response: Response,
    admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        reset_service.reset_server(conn, settings, admin, body.password, body.keep_users)
        needs_setup = auth_service.needs_setup(conn)
    state = request.app.state
    state.now_playing = NowPlaying()
    # As after a new start: there is time again to create the first admin.
    state.setup_until = time.monotonic() + auth_service.SETUP_WINDOW_S
    clear_session_cookie(response, settings)
    return ResetOut(needs_setup=needs_setup)
