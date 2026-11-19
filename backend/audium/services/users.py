"""User accounts and invites."""

import re
from dataclasses import dataclass

from sqlalchemy import Connection, func, select

from audium.auth import passwords
from audium.auth.tokens import hash_token, new_token
from audium.db.schema import api_tokens, invites, sessions, users
from audium.errors import BadRequest, Conflict, Forbidden, NotFound
from audium.util import now_ms

ROLES = ("admin", "user")
STATUSES = ("active", "disabled")
# Background of the round initial that stands for a user; the web UI maps each name to its colors.
AVATAR_COLORS = ("red", "orange", "amber", "green", "teal", "blue", "indigo", "violet", "pink", "slate")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str
    status: str
    created_at: int
    last_login_at: int | None
    avatar_color: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


_USER_COLS = (
    users.c.id,
    users.c.username,
    users.c.display_name,
    users.c.role,
    users.c.status,
    users.c.created_at,
    users.c.last_login_at,
    users.c.avatar_color,
)


def user_from_row(row) -> User:
    return User(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        role=row.role,
        status=row.status,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
        avatar_color=row.avatar_color,
    )


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    u = normalize_username(username)
    if not _USERNAME_RE.match(u):
        raise BadRequest(
            "username must be 2-32 characters: letters, digits, '.', '_' or '-', starting with a letter or digit"
        )
    return u


def validate_password(password: str) -> None:
    if not (passwords.MIN_LENGTH <= len(password) <= passwords.MAX_LENGTH):
        raise BadRequest(f"password must be {passwords.MIN_LENGTH}-{passwords.MAX_LENGTH} characters")


def count_users(conn: Connection) -> int:
    return conn.execute(select(func.count()).select_from(users)).scalar_one()


def get_user(conn: Connection, user_id: int) -> User:
    row = conn.execute(select(*_USER_COLS).where(users.c.id == user_id)).first()
    if row is None:
        raise NotFound("user not found")
    return user_from_row(row)


def find_by_username(conn: Connection, username: str):
    """Full row including password_hash, or None."""
    return conn.execute(select(users).where(users.c.username == normalize_username(username))).first()


def list_users(conn: Connection, limit: int, offset: int) -> tuple[list[User], int]:
    rows = conn.execute(select(*_USER_COLS).order_by(users.c.username).limit(limit).offset(offset)).all()
    return [user_from_row(r) for r in rows], count_users(conn)


def create_user(
    conn: Connection, username: str, password: str, role: str = "user", display_name: str | None = None
) -> User:
    u = validate_username(username)
    validate_password(password)
    if role not in ROLES:
        raise BadRequest("invalid role")
    if find_by_username(conn, u) is not None:
        raise Conflict("username already taken")
    ts = now_ms()
    user_id = conn.execute(
        users.insert().values(
            username=u,
            display_name=(display_name or "").strip()[:64] or u,
            password_hash=passwords.hash_password(password),
            role=role,
            status="active",
            created_at=ts,
            updated_at=ts,
        )
    ).inserted_primary_key[0]
    return get_user(conn, user_id)


def _active_admin_count(conn: Connection) -> int:
    return conn.execute(
        select(func.count()).select_from(users).where(users.c.role == "admin", users.c.status == "active")
    ).scalar_one()


def update_user(
    conn: Connection,
    actor: User,
    user_id: int,
    *,
    role: str | None = None,
    status: str | None = None,
    display_name: str | None = None,
    password: str | None = None,
) -> User:
    """Admin edits another account. Guards against locking everyone out."""
    target = get_user(conn, user_id)
    values: dict = {}
    if role is not None and role != target.role:
        if role not in ROLES:
            raise BadRequest("invalid role")
        if target.id == actor.id:
            raise Forbidden("you cannot change your own role")
        values["role"] = role
    if status is not None and status != target.status:
        if status not in STATUSES:
            raise BadRequest("invalid status")
        if target.id == actor.id:
            raise Forbidden("you cannot disable your own account")
        values["status"] = status
    removes_admin = (
        target.role == "admin"
        and target.status == "active"
        and (values.get("role", "admin") != "admin" or values.get("status", "active") != "active")
    )
    if removes_admin and _active_admin_count(conn) <= 1:
        raise Conflict("at least one active admin is required")
    if display_name is not None:
        values["display_name"] = display_name.strip()[:64] or target.username
    if password is not None:
        validate_password(password)
        values["password_hash"] = passwords.hash_password(password)
    if not values:
        return target
    values["updated_at"] = now_ms()
    conn.execute(users.update().where(users.c.id == user_id).values(**values))
    if values.get("status") == "disabled" or "password_hash" in values:
        # Disabling or resetting a password ends every open session and token immediately.
        conn.execute(sessions.delete().where(sessions.c.user_id == user_id))
        if values.get("status") == "disabled":
            conn.execute(api_tokens.delete().where(api_tokens.c.user_id == user_id))
    return get_user(conn, user_id)


def update_own_profile(
    conn: Connection,
    user: User,
    *,
    username: str | None = None,
    display_name: str | None = None,
    avatar_color: str | None = None,
) -> User:
    """A user edits their own account. Sessions and tokens stay valid: they hang on the id, not the name.
    avatar_color "" goes back to the accent color."""
    values: dict = {}
    if username is not None:
        u = validate_username(username)
        if u != user.username:
            if find_by_username(conn, u) is not None:
                raise Conflict("username already taken")
            values["username"] = u
    if display_name is not None:
        values["display_name"] = display_name.strip()[:64] or values.get("username", user.username)
    if avatar_color is not None:
        if avatar_color and avatar_color not in AVATAR_COLORS:
            raise BadRequest(f"avatar_color must be one of {', '.join(AVATAR_COLORS)}")
        values["avatar_color"] = avatar_color or None
    if not values:
        return user
    values["updated_at"] = now_ms()
    conn.execute(users.update().where(users.c.id == user.id).values(**values))
    return get_user(conn, user.id)


# --- Invites -------------------------------------------------------------------------------

INVITE_TTL_HOURS_DEFAULT = 7 * 24


def create_invite(conn: Connection, actor: User, role: str = "user", ttl_hours: int | None = None):
    if role not in ROLES:
        raise BadRequest("invalid role")
    ttl = ttl_hours or INVITE_TTL_HOURS_DEFAULT
    if not 1 <= ttl <= 24 * 90:
        raise BadRequest("ttl_hours must be between 1 and 2160")
    token = new_token(24)
    ts = now_ms()
    invite_id = conn.execute(
        invites.insert().values(
            token_hash=hash_token(token),
            role=role,
            created_by=actor.id,
            created_at=ts,
            expires_at=ts + ttl * 3_600_000,
        )
    ).inserted_primary_key[0]
    return invite_id, token


def list_invites(conn: Connection):
    return conn.execute(select(invites).order_by(invites.c.id.desc()).limit(200)).all()


def revoke_invite(conn: Connection, invite_id: int) -> None:
    res = conn.execute(invites.delete().where(invites.c.id == invite_id, invites.c.used_at.is_(None)))
    if res.rowcount == 0:
        raise NotFound("invite not found or already used")


def _valid_invite(conn: Connection, token: str):
    row = conn.execute(select(invites).where(invites.c.token_hash == hash_token(token))).first()
    if row is None or row.used_at is not None or row.expires_at < now_ms():
        raise NotFound("invite is invalid or expired")
    return row


def check_invite(conn: Connection, token: str) -> str:
    return _valid_invite(conn, token).role


def register_with_invite(conn: Connection, token: str, username: str, password: str, display_name: str | None) -> User:
    invite = _valid_invite(conn, token)
    user = create_user(conn, username, password, invite.role, display_name)
    conn.execute(invites.update().where(invites.c.id == invite.id).values(used_by=user.id, used_at=now_ms()))
    return user
