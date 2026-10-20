"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from audium import __version__
from audium.api import admin_library, admin_users, auth, library, system
from audium.config import Settings
from audium.db.counts import CountCache
from audium.db.engine import Database
from audium.errors import AudiumError, Forbidden
from audium.logging import get_logger
from audium.services import auth as auth_service

log = get_logger(__name__)

CSRF_HEADER = "x-requested-with"


def create_app(settings: Settings, db: Database | None = None) -> FastAPI:
    db = db or Database(settings.db_url, read_concurrency=settings.api_db_readers)

    @asynccontextmanager
    async def lifespan(_app):
        with db.write() as conn:
            token = auth_service.bootstrap(conn, settings)
        if token:
            log.warning(
                "setup.required",
                setup_token=token,
                hint="Create the admin account with this token: open /api/docs and call POST /api/v1/setup.",
            )
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

    api.include_router(system.router, prefix="/api")
    for r in (auth.router, library.router, admin_users.router, admin_library.router):
        api.include_router(r, prefix="/api/v1")

    @api.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if _csrf_suspect(request, settings.base_path):
            return _error_response(Forbidden(f"send JSON or a {CSRF_HEADER} header"))
        return await call_next(request)

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


def _csrf_suspect(request: Request, base_path: str) -> bool:
    """A foreign web page can make the browser send only "simple" requests without a CORS
    preflight: GET/HEAD, or POST with a form or text/plain body. audium never allows CORS, so
    everything else (JSON bodies, PUT/PATCH/DELETE, custom headers) can only come from audium's
    own pages or from non-browser clients. Cookies are SameSite=Lax on top of this."""
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
