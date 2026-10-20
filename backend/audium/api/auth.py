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
    InviteCheck,
    LoginIn,
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
)
from audium.config import Settings
from audium.db.engine import Database
from audium.errors import Forbidden, Unauthorized
from audium.services import auth as auth_service
from audium.services import users as user_service
from audium.services.users import User

router = APIRouter(tags=["auth"])


def _user_out(u: User) -> UserOut:
    return UserOut(**u.__dict__)


@router.get("/setup", response_model=SetupStatus)
def setup_status(db: Database = Depends(get_db)):
    with db.read() as conn:
        return SetupStatus(needs_setup=auth_service.needs_setup(conn))


@router.post("/setup", response_model=UserOut, summary="Create the first admin (needs the setup token)")
def setup(
    body: SetupIn,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        result = auth_service.complete_setup(
            conn,
            settings,
            body.setup_token,
            body.username,
            body.password,
            body.display_name,
            client_ip(request),
            request.headers.get("user-agent"),
        )
    if result is None:
        raise Forbidden("invalid setup token")
    user, session = result
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


@router.post("/auth/logout", response_model=Ok)
def logout(
    response: Response,
    principal: Principal = Depends(current_principal),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if principal.session_id is not None:
        with db.write() as conn:
            auth_service.revoke_session(conn, principal.user.id, principal.session_id)
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
