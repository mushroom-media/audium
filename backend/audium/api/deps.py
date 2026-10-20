"""Request-scoped dependencies: settings, database, authenticated principal."""

from dataclasses import dataclass

from fastapi import Depends, Request, Response

from audium.config import Settings
from audium.db.engine import Database
from audium.errors import Forbidden, Unauthorized
from audium.services import auth as auth_service
from audium.services.users import User
from audium.util import now_ms

SESSION_COOKIE = "audium_session"
_TOKEN_TOUCH_MS = 5 * 60 * 1000


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


def current_principal(request: Request) -> Principal:
    db = get_db(request)
    settings = get_settings(request)
    authz = request.headers.get("authorization", "")
    if authz[:7].lower() == "bearer ":
        with db.read() as conn:
            res = auth_service.resolve_api_token(conn, authz[7:].strip())
        if res is None:
            raise Unauthorized("invalid token")
        user, row = res
        if row.last_used_at is None or row.last_used_at + _TOKEN_TOUCH_MS < now_ms():
            with db.write() as conn:
                auth_service.touch_api_token(conn, row.token_id)
        return Principal(user, None, "token")

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized("not logged in")
    with db.read() as conn:
        res = auth_service.resolve_session(conn, token)
    if res is None:
        raise Unauthorized("session expired")
    user, row = res
    if auth_service.session_needs_touch(row):
        with db.write() as conn:
            auth_service.touch_session(conn, settings, row.session_id)
    return Principal(user, row.session_id, "session")


def current_user(principal: Principal = Depends(current_principal)) -> User:
    return principal.user


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
