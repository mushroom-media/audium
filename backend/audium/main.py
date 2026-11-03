"""FastAPI application factory."""

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from audium import __version__
from audium.analysis.similarity import VectorIndex
from audium.api import (
    admin_library,
    admin_users,
    auth,
    devices,
    discover,
    events,
    library,
    personal,
    playlists,
    setup,
    stream,
    subsonic,
    system,
    web,
)
from audium.api.devices import DeviceRegistry
from audium.api.eventbus import EventBus
from audium.api.fastpaths import Compress, CoverShortcut
from audium.auth.media import media_key
from audium.auth.secretbox import SecretBox, load_key
from audium.config import Settings
from audium.db.counts import CountCache
from audium.db.engine import Database
from audium.errors import AudiumError, Forbidden
from audium.logging import get_logger
from audium.media.transcode import Transcoder
from audium.services import auth as auth_service
from audium.services.nowplaying import NowPlaying
from audium.services.radio_suggestions import SuggestionCache

log = get_logger(__name__)

CSRF_HEADER = "x-requested-with"


def create_app(settings: Settings, db: Database | None = None) -> FastAPI:
    db = db or Database(settings.db_url, read_concurrency=settings.api_db_readers)

    bus = EventBus()

    @asynccontextmanager
    async def lifespan(_app):
        bus.bind(asyncio.get_running_loop())
        with db.write() as conn:
            open_setup = auth_service.bootstrap(conn, settings)
        if open_setup:
            log.warning(
                "setup.required",
                minutes=auth_service.SETUP_WINDOW_S // 60,
                hint="Open audium in a browser and create the admin account. After this time, restart to get more.",
            )
        api.state.vectors.warm()
        yield
        db.dispose()

    api = FastAPI(
        title="audium",
        version=__version__,
        summary="Self-hosted music streaming server",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=None if settings.base_path else lifespan,
    )
    api.state.settings = settings
    api.state.db = db
    api.state.counts = CountCache()
    api.state.transcoder = Transcoder(settings.max_transcodes)
    api.state.bus = bus
    api.state.devices = DeviceRegistry(bus)
    api.state.vectors = VectorIndex(db, directory=settings.vectors_dir)
    secret = load_key(settings)
    api.state.secrets = SecretBox(secret)
    api.state.media_key = media_key(secret)
    api.state.now_playing = NowPlaying()
    api.state.suggestions = SuggestionCache()
    api.state.setup_until = time.monotonic() + auth_service.SETUP_WINDOW_S

    api.include_router(system.router, prefix="/api")
    routers = (
        auth.router,
        library.router,
        stream.router,
        playlists.router,
        personal.router,
        events.router,
        devices.router,
        discover.router,
        discover.admin,
        admin_users.router,
        admin_library.router,
        setup.router,
    )
    for r in routers:
        api.include_router(r, prefix="/api/v1")
    if settings.subsonic_enabled:
        api.include_router(subsonic.make_router())
    api.include_router(web.make_router(settings.web_dir, settings.base_path))  # last: catch-all
    api.add_middleware(CsrfGuard, base_path=settings.base_path)
    api.add_middleware(CoverShortcut, settings=settings, db=db)
    api.add_middleware(Compress)
    if settings.app_origin_list:
        # The audium apps (another origin) call /api with a bearer token. Never with cookies
        # (allow_credentials=False), so a foreign page cannot ride on a browser session (D15a).
        api.add_middleware(
            CORSMiddleware,
            allow_origins=settings.app_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With", "If-Match", "Last-Event-ID", "Range"],
            expose_headers=["Retry-After", "ETag", "Content-Range", "Accept-Ranges", "Content-Length"],
            max_age=3600,
        )

    @api.exception_handler(AudiumError)
    async def _domain_error(_request: Request, exc: AudiumError):
        return _error_response(exc)

    if not settings.base_path:
        return api

    # Behind a reverse proxy under a sub-path: the proxy forwards the full path (no stripping).
    outer = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    outer.state.settings = settings
    outer.state.db = db

    @outer.get("/", include_in_schema=False)
    def _root_redirect():
        return RedirectResponse(settings.base_path + "/")

    outer.mount(settings.base_path, api)
    return outer


class CsrfGuard:
    """Pure ASGI middleware (no BaseHTTPMiddleware: it adds per-request overhead and gets in the
    way of streaming responses that the client abandons, e.g. when seeking)."""

    def __init__(self, app, base_path: str) -> None:
        self.app = app
        self.base_path = base_path

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and _csrf_suspect(Request(scope), self.base_path):
            response = _error_response(Forbidden(f"send JSON or a {CSRF_HEADER} header"))
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _csrf_suspect(request: Request, base_path: str) -> bool:
    """A foreign web page can make the browser send only "simple" requests without a CORS
    preflight: GET/HEAD, or POST with a form or text/plain body. audium never allows CORS, so
    everything else (JSON bodies, PUT/PATCH/DELETE, custom headers) can only come from audium's
    own pages or from non-browser clients. Cookies are SameSite=Lax on top of this.
    /rest (Subsonic) is not checked: its apps send plain form POSTs, and it never accepts the
    session cookie, so a foreign page cannot act for the user there."""
    if request.method != "POST" or "authorization" in request.headers or CSRF_HEADER in request.headers:
        return False
    if not request.url.path.removeprefix(base_path).startswith("/api/"):
        return False
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    return content_type != "application/json"


def _error_response(exc: AudiumError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if hasattr(exc, "retry_after") else None
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message, **exc.details}},
        status_code=exc.status,
        headers=headers,
    )
