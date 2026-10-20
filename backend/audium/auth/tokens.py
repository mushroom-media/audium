"""Opaque random tokens. Only their SHA-256 is stored, so a leaked database contains no usable tokens."""

import hashlib
import hmac
import secrets

API_TOKEN_PREFIX = "aud_"


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_api_token() -> str:
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
