"""GET /api/v1/events: Server-Sent Events with live changes to playlists you can see.

    id: 42
    event: playlist
    data: {"playlist_id": 7, "type": "items", "version": 13, "actor_id": 2}

Clients reload what they show when an event arrives. EventSource reconnects by itself and
sends Last-Event-ID; missed events are replayed from the playlist_events table. An event of
type "resync" means: too much happened, reload everything.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from audium.api.deps import current_user, get_db
from audium.db.engine import Database
from audium.services import playlists as svc
from audium.services.users import User

router = APIRouter(tags=["events"])

KEEPALIVE_S = 15.0


def _format(event: svc.Event) -> str:
    data = {"playlist_id": event.playlist_id, "type": event.type, "version": event.version, "actor_id": event.actor_id}
    return f"id: {event.seq}\nevent: playlist\ndata: {json.dumps(data)}\n\n"


@router.get("/events", response_class=StreamingResponse, summary="Live updates (text/event-stream)")
async def events(
    request: Request,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    bus = request.app.state.bus
    sub = bus.subscribe(user.id)  # before the catch-up query, so nothing falls in between

    def catch_up(after: int):
        with db.read() as conn:
            return svc.events_since(conn, user.id, after), svc.latest_event_seq(conn)

    async def stream():
        try:
            yield "retry: 3000\n\n"
            after = int(last_event_id) if last_event_id and last_event_id.isdigit() else None
            if after is not None:
                missed, latest = await run_in_threadpool(catch_up, after)
                if len(missed) >= 500:
                    yield f"id: {latest}\nevent: resync\ndata: {{}}\n\n"
                else:
                    for e in missed:
                        yield _format(e)
            else:
                _missed, latest = await run_in_threadpool(catch_up, 1 << 62)
                yield f"id: {latest}\nevent: hello\ndata: {{}}\n\n"
            seen = after or 0
            while True:
                if await request.is_disconnected():
                    break
                if sub.overflowed:
                    sub.overflowed = False
                    yield "event: resync\ndata: {}\n\n"
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"  # keeps proxies from closing an idle connection
                    continue
                if event.seq <= seen:
                    continue  # already delivered by the catch-up
                seen = event.seq
                yield _format(event)
        finally:
            bus.unsubscribe(sub)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # nginx: do not buffer
    )
