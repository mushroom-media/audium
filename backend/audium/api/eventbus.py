"""In-process publish/subscribe for Server-Sent Events.

The API runs as a single process (decision D09), so a set of asyncio queues is enough: sync
endpoints publish after their transaction committed, each open /events connection receives the
events its user may see. A slow client whose queue overflows is told to resync instead of
stalling everybody else.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from audium.services.playlists import Event

_QUEUE_SIZE = 200


@dataclass(frozen=True, eq=False)
class DeviceMessage:
    """A live message between one user's players (see api/devices.py). Not stored and not
    replayed, so it has no sequence number."""

    user_id: int
    event: str  # device | device-queue | device-gone | command
    data: dict[str, Any]
    to: str | None = None  # only this device's connections
    seq: None = None

    def visible_to(self, user_id: int) -> bool:
        return user_id == self.user_id


@dataclass(eq=False)
class Subscriber:
    user_id: int
    device_id: str | None = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_SIZE))
    overflowed: bool = False


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, user_id: int, device_id: str | None = None) -> Subscriber:
        sub = Subscriber(user_id, device_id)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, *events: Event | DeviceMessage | None) -> None:
        """Thread-safe; called from the threadpool by sync endpoints."""
        events = tuple(e for e in events if e is not None)
        if not events or self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._dispatch, events)

    def _dispatch(self, events: tuple[Event | DeviceMessage, ...]) -> None:
        for sub in list(self._subs):
            for event in events:
                if not event.visible_to(sub.user_id):
                    continue
                if isinstance(event, DeviceMessage) and event.to is not None and event.to != sub.device_id:
                    continue
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    sub.overflowed = True
