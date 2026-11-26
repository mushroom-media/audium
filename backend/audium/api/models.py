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
    avatar_color: str | None = Field(None, description="Background of the avatar, null = the accent color")


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
    needs_setup: bool = Field(description="No user exists yet")
    window_open: bool = Field(description="The first admin can be created right now")
    dialog_pending: bool = Field(description="The first-run dialog is not finished")
    language: Literal["de", "en"] | None = Field(description="The server language; null: not chosen yet")


class SetupIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    display_name: str | None = Field(None, max_length=64)


class RegisterIn(BaseModel):
    invite_token: str = Field(max_length=128)
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    display_name: str | None = Field(None, max_length=64)


class MeUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=64)
    username: str | None = Field(None, max_length=64, description="Also the login name in apps")
    avatar_color: str | None = Field(None, max_length=16, description='A preset color, "" for the accent color')


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
    language: Literal["server", "de", "en"]
    language_default: Literal["de", "en"] = Field(description="What language 'server' means (read-only)")
    theme: Literal["system", "dark", "light"]
    stream_quality: Literal["auto", "high", "medium", "low"]
    shortcuts: Literal["on", "off"]
    seek_keys: Literal["off", "on"] = Field(description="Plain left/right arrow keys seek 10 seconds")
    replay_gain: Literal["off", "track", "album"]
    crossfade: Literal["off", "on"]
    crossfade_s: int = Field(description="Crossfade length in seconds")
    backdrop_motion: int = Field(description="Movement of the cover backdrop in 'now playing', 0-100")
    library_tab: Literal["last", "tracks", "albums", "artists"]
    track_sort: Literal["title", "added", "year"]
    album_sort: Literal["title", "artist", "year", "added"]
    artist_role: Literal["album", "all"]
    artist_images: Literal["server", "on", "off"]
    artist_images_default: Literal["on", "off"] = Field(description="What artist_images 'server' means (read-only)")
    subsonic_api: Literal["on", "off"] = Field("on", description="The Subsonic API is on (read-only)")


class UserSettingsUpdate(BaseModel):
    language: Literal["server", "de", "en"] | None = None
    theme: Literal["system", "dark", "light"] | None = None
    stream_quality: Literal["auto", "high", "medium", "low"] | None = None
    shortcuts: Literal["on", "off"] | None = None
    seek_keys: Literal["off", "on"] | None = None
    replay_gain: Literal["off", "track", "album"] | None = None
    crossfade: Literal["off", "on"] | None = None
    crossfade_s: int | None = Field(None, ge=1, le=12)
    backdrop_motion: int | None = Field(None, ge=0, le=100)
    library_tab: Literal["last", "tracks", "albums", "artists"] | None = None
    track_sort: Literal["title", "added", "year"] | None = None
    album_sort: Literal["title", "artist", "year", "added"] | None = None
    artist_role: Literal["album", "all"] | None = None
    artist_images: Literal["server", "on", "off"] | None = None


class ServerSettings(BaseModel):
    language: Literal["de", "en"] = Field(description="Default language of the users and the server's own texts")
    artist_album_covers: Literal["on", "off"]
    artist_folder_images: Literal["on", "off"] = Field(description="folder.jpg in the artist folder as its picture")
    analysis_workers: str = Field(description='"default" (AUDIUM_ANALYSIS_WORKERS) or 1..16 processes')
    analysis_paused: Literal["off", "on"]
    analysis_schedule: Literal["always", "window"]
    analysis_from: str = Field(description='Hour "00".."23", server time')
    analysis_until: str = Field(description='Hour "00".."23" (exclusive), server time')
    subsonic_api: Literal["on", "off"] = Field(description="The Subsonic API under /rest")
    app_access: Literal["on", "off"] = Field(description="The audium apps (bearer tokens on /api)")
    model_download: Literal["on", "off"] = Field(description="Download the analysis models")


class ServerSettingsUpdate(BaseModel):
    language: Literal["de", "en"] | None = None
    artist_album_covers: Literal["on", "off"] | None = None
    artist_folder_images: Literal["on", "off"] | None = None
    analysis_workers: str | None = None
    analysis_paused: Literal["off", "on"] | None = None
    analysis_schedule: Literal["always", "window"] | None = None
    analysis_from: str | None = None
    analysis_until: str | None = None
    subsonic_api: Literal["on", "off"] | None = None
    app_access: Literal["on", "off"] | None = None
    model_download: Literal["on", "off"] | None = None


class Interfaces(BaseModel):
    """What the environment allows; the switches themselves are server settings."""

    subsonic_available: bool = Field(description="AUDIUM_SUBSONIC_ENABLED is on")
    model_download_available: bool = Field(description="AUDIUM_ANALYSIS_DOWNLOAD_MODELS is on")
    app_origins: list[str] = Field(description="AUDIUM_APP_ORIGINS: where the apps may connect from")
