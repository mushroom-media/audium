"""Signed media tokens: let `<audio src>`, `<img src>` and `EventSource` of the apps authenticate.

Those cannot send an `Authorization` header, and the apps have no cookie (another origin). An app
asks for a media token with its bearer token and appends it as `?mt=...` to stream, cover and
event URLs. The token is an HMAC over (api token id, user id, expiry), so the server keeps no
state for it; it is only accepted for those read-only GET endpoints, expires after MEDIA_TTL_MS,
and dies with the API token it was made from (logging out of the app revokes both).
"""

import base64
import hashlib
import hmac

MEDIA_TTL_MS = 12 * 3_600_000
_SIG_BYTES = 18


def media_key(secret_key: bytes) -> bytes:
    """A key of its own, derived from the server secret (never the encryption key itself)."""
    return hmac.new(secret_key, b"audium media token v1", hashlib.sha256).digest()


def _sign(key: bytes, payload: str) -> str:
    mac = hmac.new(key, payload.encode(), hashlib.sha256).digest()[:_SIG_BYTES]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def make_media_token(key: bytes, token_id: int, token_created_at: int, user_id: int, expires_at: int) -> str:
    # The token's creation time is part of it because SQLite reuses the id of a deleted row: a
    # new API token must not bring the media tokens of a revoked one back to life.
    payload = f"{token_id}.{token_created_at}.{user_id}.{expires_at}"
    return f"{payload}.{_sign(key, payload)}"


def read_media_token(key: bytes, token: str, now: int) -> tuple[int, int, int] | None:
    """(api token id, its creation time, user id) of a valid, unexpired media token, else None."""
    parts = token.split(".")
    if len(parts) != 5 or not all(p.isdigit() for p in parts[:4]):
        return None
    payload = ".".join(parts[:4])
    if not hmac.compare_digest(parts[4], _sign(key, payload)):
        return None
    token_id, created_at, user_id, expires_at = (int(p) for p in parts[:4])
    if expires_at < now:
        return None
    return token_id, created_at, user_id
