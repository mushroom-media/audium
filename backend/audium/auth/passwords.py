from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2id with library defaults (time_cost=3, 64 MiB, parallelism=4): ~50-150 ms on a Raspberry Pi 4.
_hasher = PasswordHasher()
# Verified against when the username does not exist, so response time does not reveal it.
_DUMMY_HASH = _hasher.hash("audium-dummy-password")

MIN_LENGTH = 3
MAX_LENGTH = 256


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def burn_time() -> None:
    """Spend the same time as a real verification (used for unknown users)."""
    verify_password(None, "x")
