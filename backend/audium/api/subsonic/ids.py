"""Subsonic ids are strings. Some endpoints accept ids of several kinds (getCoverArt, star,
getMusicDirectory), so every id carries a prefix: ar-12 (artist), al-12 (album), tr-12 (track),
pl-12 (playlist), ap-12 (auto-playlist), co-<hash> (cover image).

Music folders are the exception: their id is a plain number, because the Subsonic schema types
it as an integer and older apps parse it as one.
"""

import re

from audium.api.subsonic import envelope
from audium.api.subsonic.envelope import SubsonicError

ARTIST, ALBUM, TRACK, PLAYLIST, AUTO, COVER = "ar", "al", "tr", "pl", "ap", "co"
_NUMERIC = (ARTIST, ALBUM, TRACK, PLAYLIST, AUTO)
_HASH_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_ID = 2**62


def make(kind: str, value: int | str) -> str:
    return f"{kind}-{value}"


def cover(digest: str | None) -> str | None:
    return make(COVER, digest) if digest else None


def parse(value: str, *kinds: str) -> tuple[str, int | str]:
    """(kind, number) or (COVER, hash). Unknown prefixes, kinds outside `kinds` and malformed
    numbers are "not found" (70), like a missing item."""
    kind, sep, rest = value.strip().partition("-")
    if sep and kind in kinds:
        if kind == COVER:
            if _HASH_RE.match(rest):
                return kind, rest
        elif kind in _NUMERIC and rest.isdigit() and int(rest) < _MAX_ID:
            return kind, int(rest)
    raise SubsonicError(envelope.NOT_FOUND, f"not found: {value}")


def parse_one(value: str, kind: str) -> int:
    return parse(value, kind)[1]  # type: ignore[return-value]


def folder(value: str | None) -> int | None:
    """musicFolderId: a plain number (also accepted with an "mf-" prefix)."""
    if value is None or value == "":
        return None
    raw = value.strip().removeprefix("mf-")
    if not raw.isdigit():
        raise SubsonicError(envelope.NOT_FOUND, f"music folder not found: {value}")
    return int(raw)
