"""Symmetric encryption for secrets the server must be able to read back (Subsonic app passwords).

AES-256-GCM with a random 96-bit nonce per secret, stored as nonce || ciphertext+tag. The key
never sits in the database: it comes from AUDIUM_SECRET_KEY or from <data>/secret.key, which is
created with mode 0600 on first use. A database dump alone therefore reveals no app password.
"""

import hashlib
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from audium.config import Settings

_KEY_BYTES = 32
_NONCE_BYTES = 12


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise ValueError("key must be 32 bytes")
        self._aead = AESGCM(key)

    def seal(self, plaintext: str, context: bytes) -> bytes:
        """`context` is authenticated but not stored: the same value must be given to `open`
        (binds a secret to its row, so it cannot be copied to another user)."""
        nonce = secrets.token_bytes(_NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext.encode(), context)

    def open(self, sealed: bytes, context: bytes) -> str | None:
        """The plaintext, or None if the data was changed or sealed with another key."""
        if len(sealed) <= _NONCE_BYTES:
            return None
        try:
            return self._aead.decrypt(sealed[:_NONCE_BYTES], sealed[_NONCE_BYTES:], context).decode()
        except (InvalidTag, UnicodeDecodeError):
            return None


def load_key(settings: Settings) -> bytes:
    if settings.secret_key:
        # Any passphrase works; hashing makes it a key of the right length.
        return hashlib.sha256(settings.secret_key.encode()).digest()
    return _key_file(settings.secret_key_file)


def _key_file(path: Path) -> bytes:
    try:
        key = path.read_bytes()
    except FileNotFoundError:
        key = secrets.token_bytes(_KEY_BYTES)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written completely under a temporary name, then linked into place: nobody ever reads a
        # half-written key, and if another process was faster its key wins.
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return _key_file(path)
        finally:
            tmp.unlink()
        return key
    if len(key) != _KEY_BYTES:
        raise RuntimeError(f"{path} is damaged: expected {_KEY_BYTES} bytes, found {len(key)}")
    return key
