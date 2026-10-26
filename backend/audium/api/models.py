"""Request/response models shared by the routers (they define the OpenAPI schema)."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(None, description="Pass as `cursor` to get the next page")
    total: int | None = Field(None, description="Total number of items for this query")


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class Ok(BaseModel):
    ok: bool = True


# --- Users / auth --------------------------------------------------------------------------

Role = Literal["admin", "user"]


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: Role
    status: Literal["active", "disabled"]
    created_at: int
    last_login_at: int | None


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class AppLoginIn(LoginIn):
    device: str | None = Field(None, max_length=64, description='Shown in the token list, e.g. "Pixel 8"')


class AppLoginOut(BaseModel):
    token: str = Field(description="Bearer token for all further requests; logging out revokes it")
    user: "UserOut"


class MediaTokenOut(BaseModel):
    token: str = Field(description="Append as ?mt=... to stream, cover and event URLs")
    expires_at: int


class SetupStatus(BaseModel):
    needs_setup: bool


class SetupIn(BaseModel):
    setup_token: str = Field(max_length=128)
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    display_name: str | None = Field(None, max_length=64)


class RegisterIn(BaseModel):
    invite_token: str = Field(max_length=128)
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    display_name: str | None = Field(None, max_length=64)


class MeUpdate(BaseModel):
    display_name: str = Field(max_length=64)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class SessionOut(BaseModel):
    id: int
    created_at: int
    last_seen_at: int
    user_agent: str | None
    ip: str | None
    current: bool


class TokenCreate(BaseModel):
    name: str = Field(max_length=64)


class TokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: int
    last_used_at: int | None


class TokenCreated(TokenOut):
    token: str = Field(description="Shown only once")


class AppPasswordCreate(BaseModel):
    name: str = Field(max_length=64, description='Which app or device, e.g. "Symfonium Handy"')


class AppPasswordOut(BaseModel):
    id: int
    name: str
    prefix: str = Field(description="First characters of the password")
    created_at: int
    last_used_at: int | None
    last_client: str | None = Field(description="Name of the app that used it last")


class AppPasswordCreated(AppPasswordOut):
    password: str = Field(description="Shown only once")


class UserCreate(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    role: Role = "user"
    display_name: str | None = Field(None, max_length=64)


class UserUpdate(BaseModel):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None
    display_name: str | None = Field(None, max_length=64)
    password: str | None = Field(None, max_length=256)


class InviteCreate(BaseModel):
    role: Role = "user"
    ttl_hours: int | None = Field(None, ge=1, le=2160)


class InviteOut(BaseModel):
    id: int
    role: Role
    created_at: int
    expires_at: int
    used_at: int | None
    used_by: int | None


class InviteCreated(InviteOut):
    token: str = Field(description="Shown only once; the invite link is <base>/invite/<token>")


class InviteCheck(BaseModel):
    valid: bool
    role: Role


class UserSettings(BaseModel):
    theme: Literal["system", "dark", "light"]
    stream_quality: Literal["auto", "high", "medium", "low"]
    shortcuts: Literal["on", "off"]


class UserSettingsUpdate(BaseModel):
    theme: Literal["system", "dark", "light"] | None = None
    stream_quality: Literal["auto", "high", "medium", "low"] | None = None
    shortcuts: Literal["on", "off"] | None = None


class ServerSettings(BaseModel):
    artist_album_covers: Literal["on", "off"]


class ServerSettingsUpdate(BaseModel):
    artist_album_covers: Literal["on", "off"] | None = None
