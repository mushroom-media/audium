"""Request-scoped dependencies: settings, database, authenticated principal."""

from dataclasses import dataclass

from fastapi import Depends, Query, Request, Response
from sqlalchemy.exc import OperationalError
from starlette.concurrency import run_in_threadpool

from audium.auth.media import read_media_token
from audium.config import Settings
from audium.db.engine import Database
from audium.errors import Forbidden, Unauthorized
from audium.logging import get_logger
from audium.services import auth as auth_service
from audium.services import view_prefs
from audium.services.server_settings import server_setting
from audium.services.users import User
from audium.util import now_ms

log = get_logger(__name__)

SESSION_COOKIE = "audium_session"
_TOKEN_TOUCH_MS = 5 * 60 * 1000
_TOUCH_WAIT_MS = 500


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def client_ip(request: Request) -> str:
    # uvicorn already replaced this with X-Forwarded-For when the peer is a trusted proxy.
    return request.client.host if request.client else "unknown"


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: int | None  # None when authenticated with an API token
    via: str  # session | token
    token_id: int | None = None  # the API token; None for sessions


def current_principal(request: Request) -> Principal:
    return _principal(request)


def _principal(request: Request, urgent: bool = False) -> Principal:
    db = get_db(request)
    settings = get_settings(request)
    authz = request.headers.get("authorization", "")
    if authz[:7].lower() == "bearer ":
        with db.read(urgent) as conn:
            res = auth_service.resolve_api_token(conn, authz[7:].strip())
            apps_on = server_setting(conn, "app_access") == "on"
        if res is None:
            raise Unauthorized("invalid token")
        if not apps_on:
            raise Forbidden("app access is turned off on this server")
        user, row = res
        if row.last_used_at is None or row.last_used_at + _TOKEN_TOUCH_MS < now_ms():
            _best_effort(db, lambda conn: auth_service.touch_api_token(conn, row.token_id))
        return Principal(user, None, "token", row.token_id)

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized("not logged in")
    with db.read(urgent) as conn:
        res = auth_service.resolve_session(conn, token)
    if res is None:
        raise Unauthorized("session expired")
    user, row = res
    if auth_service.session_needs_touch(row):
        _best_effort(db, lambda conn: auth_service.touch_session(conn, settings, row.session_id))
    return Principal(user, row.session_id, "session")


def _best_effort(db: Database, write) -> None:
    """Bookkeeping writes (sliding session expiry, last use of a token): when another writer
    holds the database (a long scan or analysis step), skip them instead of making the request
    wait and fail. The next request does them."""
    try:
        with db.write(busy_timeout_ms=_TOUCH_WAIT_MS) as conn:
            write(conn)
    except OperationalError as e:
        log.info("auth.touch_skipped", error=str(e.orig))


def current_user(principal: Principal = Depends(current_principal)) -> User:
    return principal.user


async def viewer(request: Request, user: User = Depends(current_user)) -> User:
    """The current user, with their display preferences applied to this request (see
    services/view_prefs.py), e.g. for endpoints that list artists. Async on purpose: a context
    variable set here reaches the endpoint; one set in a sync dependency (run in a copied
    context in the threadpool) would not."""

    def load() -> bool:
        with get_db(request).read() as conn:
            return view_prefs.wants_artist_album_covers(conn, user.id)

    # Read in the threadpool, but set here: the thread runs in a copy of this context.
    view_prefs.artist_album_covers.set(await run_in_threadpool(load))
    return user


def media_user(
    request: Request,
    mt: str | None = Query(None, max_length=256, description="Media token of an app (see /auth/media-token)"),
) -> User:
    """For streams, covers and live updates: also accepts a signed media token in the URL, because
    `<audio>`, `<img>` and `EventSource` of the apps cannot send an Authorization header."""
    return _media_user(request, mt)


def stream_user(
    request: Request,
    mt: str | None = Query(None, max_length=256, description="Media token of an app (see /auth/media-token)"),
) -> User:
    """media_user past the queue of database reads: music starts at once, whatever else is loading."""
    return _media_user(request, mt, urgent=True)


def _media_user(request: Request, mt: str | None, urgent: bool = False) -> User:
    if not mt:
        return _principal(request, urgent).user
    found = read_media_token(request.app.state.media_key, mt, now_ms())
    if found is None:
        raise Unauthorized("media token expired")
    with get_db(request).read(urgent) as conn:
        user = auth_service.resolve_api_token_id(conn, *found)
    if user is None:
        raise Unauthorized("media token revoked")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise Forbidden("admin only")
    return user


def _cookie_secure(request: Request, settings: Settings) -> bool:
    if settings.cookie_secure == "auto":
        return request.url.scheme == "https"
    return settings.cookie_secure == "true"


def set_session_cookie(response: Response, request: Request, settings: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86_400,
        path=settings.base_path or "/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request, settings),
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(SESSION_COOKIE, path=settings.base_path or "/")
