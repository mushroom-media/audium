"""Who is calling: u + p (plain or enc:hex), u + t + s (token) against app passwords, or an
OpenSubsonic apiKey (an audium API token). Never the login password, never the session cookie."""

from audium.api.deps import client_ip
from audium.api.subsonic import envelope
from audium.api.subsonic.envelope import SubsonicError
from audium.auth import ratelimit
from audium.services import app_passwords
from audium.services import auth as auth_service
from audium.services.users import User
from audium.util import now_ms

_IP_LIMIT_FACTOR = 3  # as for the web login
_TOKEN_TOUCH_MS = 5 * 60 * 1000


def authenticate(call) -> User:
    username = call.get("u")
    api_key = call.get("apiKey")
    if api_key is not None:
        if username is not None:
            raise SubsonicError(envelope.CONFLICTING_AUTH, "apiKey must not be combined with u")
        return _by_api_key(call, api_key)
    if not username:
        raise SubsonicError(envelope.MISSING_PARAMETER, "required parameter is missing: u")

    token, salt, password = call.get("t"), call.get("s"), call.get("p")
    if token is not None or salt is not None:
        if not token or not salt:
            raise SubsonicError(envelope.MISSING_PARAMETER, "token authentication needs both t and s")
        check = app_passwords.token_check(token, salt)
    elif password is not None:
        check = app_passwords.plain_check(_decode_password(password))
    else:
        raise SubsonicError(envelope.MISSING_PARAMETER, "required parameter is missing: p (or t and s)")

    settings, db = call.settings, call.db
    now = now_ms()
    window = settings.login_window_minutes * 60_000
    limit = settings.login_max_attempts
    user_key = f"subsonic:user:{username.strip().lower()[:64]}"
    ip_key = f"subsonic:ip:{client_ip(call.request)}"
    with db.read() as conn:
        wait = max(
            ratelimit.retry_after(conn, user_key, now, window, limit),
            ratelimit.retry_after(conn, ip_key, now, window, limit * _IP_LIMIT_FACTOR),
        )
        if wait:
            raise SubsonicError(envelope.WRONG_CREDENTIALS, f"too many failed logins, try again in {wait} s")
        match = app_passwords.verify(conn, call.state.secrets, username, check)
        had_failures = match is not None and ratelimit.failures(conn, user_key, now, window) > 0
    if match is None:
        with db.write() as conn:
            ratelimit.register_failure(conn, user_key, now, window)
            ratelimit.register_failure(conn, ip_key, now, window)
        # Same answer for unknown user, wrong password and disabled account.
        raise SubsonicError(envelope.WRONG_CREDENTIALS, "wrong username or password")
    if match.needs_touch or had_failures:
        with db.write() as conn:
            app_passwords.touch(conn, match.password_id, call.get("c"))
            if had_failures:
                ratelimit.reset(conn, user_key)
    return match.user


def _by_api_key(call, api_key: str) -> User:
    with call.db.read() as conn:
        res = auth_service.resolve_api_token(conn, api_key)
    if res is None:
        raise SubsonicError(envelope.INVALID_API_KEY, "invalid API key")
    user, row = res
    if row.last_used_at is None or row.last_used_at + _TOKEN_TOUCH_MS < now_ms():
        with call.db.write() as conn:
            auth_service.touch_api_token(conn, row.token_id)
    return user


def _decode_password(p: str) -> str:
    if not p.startswith("enc:"):
        return p
    try:
        return bytes.fromhex(p[4:]).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise SubsonicError(envelope.WRONG_CREDENTIALS, "wrong username or password") from exc
