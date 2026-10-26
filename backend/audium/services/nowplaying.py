"""What users are listening to right now, as reported by Subsonic apps (scrobble with
submission=false). In memory only: the API is a single process (D09) and the information is
worthless after a restart anyway. Each user only ever sees their own entries (privacy)."""

import threading
from dataclasses import dataclass

from audium.util import now_ms

_GRACE_MS = 60_000  # an entry lives for the track's length plus this
_MAX_PER_USER = 10  # one per app/device


@dataclass(frozen=True)
class Entry:
    user_id: int
    track_id: int
    client: str | None
    started_at: int
    expires_at: int


class NowPlaying:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_user: dict[int, dict[str | None, Entry]] = {}

    def report(self, user_id: int, track_id: int, duration_ms: int, client: str | None) -> None:
        now = now_ms()
        entry = Entry(user_id, track_id, client, now, now + duration_ms + _GRACE_MS)
        with self._lock:
            mine = self._by_user.setdefault(user_id, {})
            mine[client] = entry  # a new track on the same app replaces the previous one
            if len(mine) > _MAX_PER_USER:
                oldest = min(mine, key=lambda c: mine[c].started_at)
                del mine[oldest]

    def for_user(self, user_id: int) -> list[Entry]:
        now = now_ms()
        with self._lock:
            mine = self._by_user.get(user_id, {})
            for client in [c for c, e in mine.items() if e.expires_at < now]:
                del mine[client]
            return sorted(mine.values(), key=lambda e: e.started_at, reverse=True)
