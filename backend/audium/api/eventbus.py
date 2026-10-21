"""In-process publish/subscribe for Server-Sent Events.

The API runs as a single process (decision D09), so a set of asyncio queues is enough: sync
endpoints publish after their transaction committed, each open /events connection receives the
events its user may see. A slow client whose queue overflows is told to resync instead of
stalling everybody else.
"""

import asyncio
from dataclasses import dataclass, field

from audium.services.playlists import Event

_QUEUE_SIZE = 200


@dataclass(eq=False)
class Subscriber:
    user_id: int
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_SIZE))
    overflowed: bool = False


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, user_id: int) -> Subscriber:
        sub = Subscriber(user_id)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, *events: Event | None) -> None:
        """Thread-safe; called from the threadpool by sync endpoints."""
        events = tuple(e for e in events if e is not None)
        if not events or self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._dispatch, events)

    def _dispatch(self, events: tuple[Event, ...]) -> None:
        for sub in list(self._subs):
            for event in events:
                if not event.visible_to(sub.user_id):
                    continue
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    sub.overflowed = True
