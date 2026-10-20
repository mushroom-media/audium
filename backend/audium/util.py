import time
import unicodedata

_MAX_TEXT = 1024


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def clean_text(value: object, max_len: int = _MAX_TEXT) -> str | None:
    """Turn a raw tag value into a trimmed string, or None if it is empty."""
    if value is None:
        return None
    s = str(value).replace("\x00", "").strip()
    return s[:max_len] or None


def norm(s: str) -> str:
    """Case- and accent-insensitive form used for grouping and lookups."""
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def sort_key(s: str, articles: tuple[str, ...] = ()) -> str:
    """Normalized sort key; leading articles ("The Beatles") are moved out of the way."""
    n = norm(s)
    for a in articles:
        if n.startswith(a + " ") and len(n) > len(a) + 1:
            return n[len(a) + 1 :]
    return n
