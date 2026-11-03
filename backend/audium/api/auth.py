import time

from fastapi import APIRouter, Depends, Request, Response

from audium.api.deps import (
    Principal,
    clear_session_cookie,
    client_ip,
    current_principal,
    current_user,
    get_db,
    get_settings,
    set_session_cookie,
)
from audium.api.models import (
    AppLoginIn,
    AppLoginOut,
    AppPasswordCreate,
    AppPasswordCreated,
    AppPasswordOut,
    InviteCheck,
    LoginIn,
    MediaTokenOut,
    MeUpdate,
    Ok,
    PasswordChange,
    RegisterIn,
    SessionOut,
    SetupIn,
    SetupStatus,
    TokenCreate,
    TokenCreated,
    TokenOut,
    UserOut,
    UserSettings,
    UserSettingsUpdate,
)
from audium.auth.media import MEDIA_TTL_MS, make_media_token
from audium.config import Settings
from audium.db.engine import Database
from audium.errors import Conflict, Forbidden, Unauthorized
from audium.services import app_passwords
from audium.services import auth as auth_service
from audium.services import settings as settings_service
from audium.services import users as user_service
from audium.services.server_settings import server_setting
from audium.services.users import User
from audium.util import now_ms

router = APIRouter(tags=["auth"])


def _user_out(u: User) -> UserOut:
    return UserOut(**u.__dict__)


def _setup_window_open(request: Request) -> bool:
    return time.monotonic() < request.app.state.setup_until


@router.get("/setup", response_model=SetupStatus)
def setup_status(request: Request, db: Database = Depends(get_db)):
    with db.read() as conn:
        needs = auth_service.needs_setup(conn)
        return SetupStatus(
            needs_setup=needs,
            window_open=needs and _setup_window_open(request),
            dialog_pending=auth_service.setup_pending(conn),
        )


@router.post("/setup", response_model=UserOut, summary="Create the first admin (for a while after the server started)")
def setup(
    body: SetupIn,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        user, session = auth_service.complete_setup(
            conn,
            settings,
            body.username,
            body.password,
            body.display_name,
            client_ip(request),
            request.headers.get("user-agent"),
            _setup_window_open(request),
        )
    set_session_cookie(response, request, settings, session.token)
    return _user_out(user)


@router.post("/auth/login", response_model=UserOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        result = auth_service.login(
            conn,
            settings,
            body.username,
            body.password,
            client_ip(request),
            request.headers.get("user-agent"),
        )
    if result is None:
        raise Unauthorized("invalid username or password")
    user, session = result
    set_session_cookie(response, request, settings, session.token)
    return _user_out(user)


@router.post(
    "/auth/app-login",
    response_model=AppLoginOut,
    summary="Log in from an audium app: returns a bearer token instead of a cookie",
)
def app_login(
    body: AppLoginIn, request: Request, db: Database = Depends(get_db), settings: Settings = Depends(get_settings)
):
    with db.write() as conn:
        if auth_service.needs_setup(conn):
            raise Conflict("this server is not set up yet")
        if server_setting(conn, "app_access") != "on":
            raise Forbidden("app access is turned off on this server")
        result = auth_service.app_login(conn, settings, body.username, body.password, client_ip(request), body.device)
    if result is None:
        raise Unauthorized("invalid username or password")
    user, _token_id, token = result
    return {"token": token, "user": _user_out(user)}


@router.get(
    "/auth/media-token",
    response_model=MediaTokenOut,
    summary="Signed token for stream, cover and event URLs of an app (they cannot send headers)",
)
def media_token(request: Request, principal: Principal = Depends(current_principal), db: Database = Depends(get_db)):
    if principal.token_id is None:
        raise Forbidden("media tokens are for API tokens; the web UI uses its cookie")
    with db.read() as conn:
        created_at = auth_service.api_token_created_at(conn, principal.token_id)
    expires_at = now_ms() + MEDIA_TTL_MS
    key = request.app.state.media_key
    token = make_media_token(key, principal.token_id, created_at, principal.user.id, expires_at)
    return {"token": token, "expires_at": expires_at}


@router.post("/auth/logout", response_model=Ok, summary="End the session, or revoke the token of an app")
def logout(
    response: Response,
    principal: Principal = Depends(current_principal),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if principal.session_id is not None:
        with db.write() as conn:
            auth_service.revoke_session(conn, principal.user.id, principal.session_id)
    elif principal.token_id is not None:
        with db.write() as conn:
            auth_service.revoke_api_token(conn, principal.user.id, principal.token_id)
    clear_session_cookie(response, settings)
    return Ok()


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.patch("/auth/me", response_model=UserOut)
def update_me(body: MeUpdate, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        updated = user_service.update_user(conn, user, user.id, display_name=body.display_name)
    return _user_out(updated)


@router.post("/auth/me/password", response_model=Ok, summary="Change own password (logs out other sessions)")
def change_password(
    body: PasswordChange, principal: Principal = Depends(current_principal), db: Database = Depends(get_db)
):
    with db.write() as conn:
        auth_service.change_own_password(
            conn, principal.user, body.current_password, body.new_password, principal.session_id
        )
    return Ok()


@router.get("/auth/sessions", response_model=list[SessionOut])
def my_sessions(principal: Principal = Depends(current_principal), db: Database = Depends(get_db)):
    with db.read() as conn:
        rows = auth_service.list_sessions(conn, principal.user.id)
    return [SessionOut(**r._mapping, current=r.id == principal.session_id) for r in rows]


@router.delete("/auth/sessions/{session_id}", response_model=Ok)
def revoke_my_session(session_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        auth_service.revoke_session(conn, user.id, session_id)
    return Ok()


@router.get("/auth/tokens", response_model=list[TokenOut])
def my_tokens(user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return [TokenOut(**r._mapping) for r in auth_service.list_api_tokens(conn, user.id)]


@router.post("/auth/tokens", response_model=TokenCreated, summary="Create an API token for other clients")
def create_token(body: TokenCreate, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        token_id, token = auth_service.create_api_token(conn, user.id, body.name)
        row = next(r for r in auth_service.list_api_tokens(conn, user.id) if r.id == token_id)
    return TokenCreated(**row._mapping, token=token)


@router.delete("/auth/tokens/{token_id}", response_model=Ok)
def delete_token(token_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        auth_service.revoke_api_token(conn, user.id, token_id)
    return Ok()


@router.get("/auth/app-passwords", response_model=list[AppPasswordOut], summary="Your app passwords (Subsonic apps)")
def my_app_passwords(user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return app_passwords.list_for_user(conn, user.id)


@router.post(
    "/auth/app-passwords",
    response_model=AppPasswordCreated,
    status_code=201,
    summary="Create a password for a Subsonic app (shown only once)",
)
def create_app_password(
    body: AppPasswordCreate, request: Request, user: User = Depends(current_user), db: Database = Depends(get_db)
):
    with db.write() as conn:
        out, password = app_passwords.create(conn, request.app.state.secrets, user.id, body.name)
    return {**out, "password": password}


@router.delete("/auth/app-passwords/{password_id}", response_model=Ok, summary="Revoke an app password")
def revoke_app_password(password_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        app_passwords.revoke(conn, user.id, password_id)
    return Ok()


@router.get("/invites/{token}", response_model=InviteCheck)
def check_invite(token: str, db: Database = Depends(get_db)):
    with db.read() as conn:
        role = user_service.check_invite(conn, token)
    return InviteCheck(valid=True, role=role)


@router.post("/auth/register", response_model=UserOut, summary="Create an account with an invite token")
def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        user = user_service.register_with_invite(
            conn, body.invite_token, body.username, body.password, body.display_name
        )
        session = auth_service.create_session(
            conn, settings, user.id, client_ip(request), request.headers.get("user-agent")
        )
    set_session_cookie(response, request, settings, session.token)
    return _user_out(user)


def _settings_out(conn, settings: dict) -> dict:
    return {
        **settings,
        "artist_images_default": server_setting(conn, "artist_album_covers"),
        "subsonic_api": server_setting(conn, "subsonic_api"),
    }


@router.get("/auth/me/settings", response_model=UserSettings)
def my_settings(user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return _settings_out(conn, settings_service.get_settings(conn, user.id))


@router.patch("/auth/me/settings", response_model=UserSettings)
def update_my_settings(body: UserSettingsUpdate, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        return _settings_out(conn, settings_service.update_settings(conn, user.id, body.model_dump(exclude_none=True)))
