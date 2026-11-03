"""Login, sessions, API tokens and first-run setup."""

from dataclasses import dataclass

from sqlalchemy import Connection, select

from audium.auth import passwords, ratelimit
from audium.auth.tokens import hash_token, new_api_token, new_token
from audium.config import Settings
from audium.db.schema import api_tokens, sessions, users
from audium.db.state import delete_state, get_state, set_state
from audium.errors import BadRequest, Conflict, Forbidden, NotFound, RateLimited
from audium.logging import get_logger
from audium.services.users import (
    User,
    count_users,
    create_user,
    find_by_username,
    user_from_row,
    validate_password,
)
from audium.util import now_ms

log = get_logger(__name__)

SETUP_STATE_KEY = "setup.state"  # "pending": the first-run dialog is not finished; "done"
_OLD_SETUP_TOKEN_KEY = "setup.token_hash"  # versions before the dialog
# How long after the start of the server the first admin can be created in the browser.
SETUP_WINDOW_S = 30 * 60
_SETUP_MIN_PASSWORD = 8
_LAST_SEEN_RESOLUTION_MS = 5 * 60 * 1000
_IP_LIMIT_FACTOR = 3  # one address may fail more often than one username (NAT, households)


@dataclass(frozen=True)
class Session:
    id: int
    token: str  # only known right after creation
    expires_at: int


# --- Login ---------------------------------------------------------------------------------


def login(conn: Connection, settings: Settings, username: str, password: str, ip: str, ua: str | None):
    """A new browser session, or None for wrong credentials."""
    row = check_credentials(conn, settings, username, password, ip)
    if row is None:
        return None
    session = create_session(conn, settings, row.id, ip, ua)
    return user_from_row(row), session


def app_login(conn: Connection, settings: Settings, username: str, password: str, ip: str, device: str | None):
    """A new API token for an audium app (same checks and rate limit as the web login), or None."""
    row = check_credentials(conn, settings, username, password, ip)
    if row is None:
        return None
    name = f"App: {(device or '').strip()[:50] or 'audium'}"
    token_id, token = create_api_token(conn, row.id, name)
    return user_from_row(row), token_id, token


def check_credentials(conn: Connection, settings: Settings, username: str, password: str, ip: str):
    """The user's row if the password is right and the account active, else None (counted against
    the rate limit; raises RateLimited while it is exceeded)."""
    now = now_ms()
    window = settings.login_window_minutes * 60_000
    limit = settings.login_max_attempts
    user_key = f"user:{username.strip().lower()[:64]}"
    ip_key = f"ip:{ip}"
    wait = max(
        ratelimit.retry_after(conn, user_key, now, window, limit),
        ratelimit.retry_after(conn, ip_key, now, window, limit * _IP_LIMIT_FACTOR),
    )
    if wait:
        raise RateLimited(wait)

    row = find_by_username(conn, username)
    ok = passwords.verify_password(row.password_hash if row else None, password)
    if not ok or row.status != "active":
        ratelimit.register_failure(conn, user_key, now, window)
        ratelimit.register_failure(conn, ip_key, now, window)
        log.info("auth.login_failed", username=username[:64], ip=ip)
        # The caller commits (so the failure counts) and then answers 401. Same answer for
        # unknown user, wrong password and disabled account.
        return None

    ratelimit.reset(conn, user_key)
    values = {"last_login_at": now}
    if passwords.needs_rehash(row.password_hash):
        values["password_hash"] = passwords.hash_password(password)
    conn.execute(users.update().where(users.c.id == row.id).values(**values))
    log.info("auth.login", user_id=row.id, ip=ip)
    return row


def change_own_password(conn: Connection, user: User, current: str, new: str, keep_session_id: int | None):
    row = conn.execute(select(users.c.password_hash).where(users.c.id == user.id)).first()
    if row is None or not passwords.verify_password(row.password_hash, current):
        raise Forbidden("current password is wrong")
    validate_password(new)
    conn.execute(
        users.update()
        .where(users.c.id == user.id)
        .values(password_hash=passwords.hash_password(new), updated_at=now_ms())
    )
    # Log out everywhere else.
    q = sessions.delete().where(sessions.c.user_id == user.id)
    if keep_session_id is not None:
        q = q.where(sessions.c.id != keep_session_id)
    conn.execute(q)


# --- Sessions ------------------------------------------------------------------------------


def create_session(conn: Connection, settings: Settings, user_id: int, ip: str | None, ua: str | None):
    token = new_token()
    now = now_ms()
    expires = now + settings.session_ttl_days * 86_400_000
    session_id = conn.execute(
        sessions.insert().values(
            user_id=user_id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=expires,
            user_agent=(ua or "")[:256] or None,
            ip=ip,
        )
    ).inserted_primary_key[0]
    return Session(id=session_id, token=token, expires_at=expires)


def resolve_session(conn: Connection, token: str):
    """(user, session_row) for a valid session token, else None. Read-only."""
    row = conn.execute(
        select(
            users,
            sessions.c.id.label("session_id"),
            sessions.c.last_seen_at,
            sessions.c.expires_at,
        )
        .join(users, users.c.id == sessions.c.user_id)
        .where(sessions.c.token_hash == hash_token(token))
    ).first()
    if row is None or row.expires_at < now_ms() or row.status != "active":
        return None
    return user_from_row(row), row


def session_needs_touch(session_row) -> bool:
    return session_row.last_seen_at + _LAST_SEEN_RESOLUTION_MS < now_ms()


def touch_session(conn: Connection, settings: Settings, session_id: int) -> None:
    """Sliding expiry. Called at most every few minutes per session to keep reads write-free."""
    now = now_ms()
    conn.execute(
        sessions.update()
        .where(sessions.c.id == session_id)
        .values(last_seen_at=now, expires_at=now + settings.session_ttl_days * 86_400_000)
    )


def list_sessions(conn: Connection, user_id: int):
    return conn.execute(
        select(
            sessions.c.id,
            sessions.c.created_at,
            sessions.c.last_seen_at,
            sessions.c.user_agent,
            sessions.c.ip,
        )
        .where(sessions.c.user_id == user_id, sessions.c.expires_at > now_ms())
        .order_by(sessions.c.last_seen_at.desc())
    ).all()


def revoke_session(conn: Connection, user_id: int, session_id: int) -> None:
    res = conn.execute(sessions.delete().where(sessions.c.id == session_id, sessions.c.user_id == user_id))
    if res.rowcount == 0:
        raise NotFound("session not found")


def prune_sessions(conn: Connection) -> None:
    conn.execute(sessions.delete().where(sessions.c.expires_at < now_ms()))


# --- API tokens ----------------------------------------------------------------------------


def create_api_token(conn: Connection, user_id: int, name: str):
    token = new_api_token()
    token_id = conn.execute(
        api_tokens.insert().values(
            user_id=user_id,
            name=name.strip()[:64] or "token",
            token_hash=hash_token(token),
            prefix=token[:10],
            created_at=now_ms(),
        )
    ).inserted_primary_key[0]
    return token_id, token


def resolve_api_token(conn: Connection, token: str):
    row = conn.execute(
        select(users, api_tokens.c.id.label("token_id"), api_tokens.c.last_used_at)
        .join(users, users.c.id == api_tokens.c.user_id)
        .where(api_tokens.c.token_hash == hash_token(token))
    ).first()
    if row is None or row.status != "active":
        return None
    return user_from_row(row), row


def resolve_api_token_id(conn: Connection, token_id: int, created_at: int, user_id: int):
    """The active user of an API token that still exists (for media tokens), else None."""
    row = conn.execute(
        select(users)
        .join(api_tokens, api_tokens.c.user_id == users.c.id)
        .where(api_tokens.c.id == token_id, api_tokens.c.created_at == created_at, users.c.id == user_id)
    ).first()
    if row is None or row.status != "active":
        return None
    return user_from_row(row)


def api_token_created_at(conn: Connection, token_id: int) -> int:
    return conn.execute(select(api_tokens.c.created_at).where(api_tokens.c.id == token_id)).scalar_one()


def touch_api_token(conn: Connection, token_id: int) -> None:
    conn.execute(api_tokens.update().where(api_tokens.c.id == token_id).values(last_used_at=now_ms()))


def list_api_tokens(conn: Connection, user_id: int):
    return conn.execute(
        select(
            api_tokens.c.id,
            api_tokens.c.name,
            api_tokens.c.prefix,
            api_tokens.c.created_at,
            api_tokens.c.last_used_at,
        )
        .where(api_tokens.c.user_id == user_id)
        .order_by(api_tokens.c.id)
    ).all()


def revoke_api_token(conn: Connection, user_id: int, token_id: int) -> None:
    res = conn.execute(api_tokens.delete().where(api_tokens.c.id == token_id, api_tokens.c.user_id == user_id))
    if res.rowcount == 0:
        raise NotFound("token not found")


# --- First-run setup -----------------------------------------------------------------------


def bootstrap(conn: Connection, settings: Settings) -> bool:
    """Called once when the API starts. True: the first admin has to be created in the browser.

    With AUDIUM_ADMIN_USER/PASSWORD set and no users yet, the admin is created directly.
    The state of the first-run dialog is decided once: an installation that already has users
    (from before the dialog) never sees it, one that restarts in the middle of it continues.
    """
    delete_state(conn, _OLD_SETUP_TOKEN_KEY)
    has_users = count_users(conn) > 0
    if get_state(conn, SETUP_STATE_KEY) is None:
        set_state(conn, SETUP_STATE_KEY, "done" if has_users else "pending")
    if has_users:
        return False
    if settings.admin_user and settings.admin_password:
        user = create_user(conn, settings.admin_user, settings.admin_password, role="admin")
        log.info("auth.admin_created_from_env", username=user.username)
        return False
    return True


def needs_setup(conn: Connection) -> bool:
    return count_users(conn) == 0


def setup_pending(conn: Connection) -> bool:
    return get_state(conn, SETUP_STATE_KEY) == "pending"


def setup_holds_scan(conn: Connection, settings: Settings) -> bool:
    """Scans wait for the first-run dialog, where the admin picks the folders and decides about
    the analysis. Unless the instance is configured through the environment: it then has to work
    without anyone opening a browser. An unknown state (the API has not started yet) waits too."""
    if settings.library_roots or (settings.admin_user and settings.admin_password):
        return False
    return get_state(conn, SETUP_STATE_KEY) != "done"


def finish_setup(conn: Connection) -> None:
    set_state(conn, SETUP_STATE_KEY, "done")


def complete_setup(
    conn: Connection,
    settings: Settings,
    username: str,
    password: str,
    display_name: str | None,
    ip: str,
    ua: str | None,
    window_open: bool,
):
    """Creates the first admin. Whoever opens a new instance first gets it, so this is only
    possible for a while after the start; AUDIUM_ADMIN_* avoids that moment altogether."""
    if count_users(conn) > 0:
        raise Conflict("setup is already complete")
    if not window_open:
        raise Forbidden("the time for the setup has run out")
    if len(password) < _SETUP_MIN_PASSWORD:
        raise BadRequest(f"the admin password needs at least {_SETUP_MIN_PASSWORD} characters")
    user = create_user(conn, username, password, role="admin", display_name=display_name)
    session = create_session(conn, settings, user.id, ip, ua)
    log.info("auth.setup_complete", username=user.username)
    return user, session
