"""Remote control between one user's own players ("Gerät steuern").

Every open web player is a device: it connects to /events with ?device=<id>&name=…&kind=… and
reports what it plays with PUT /devices/{id}/state. Another device of the same user (later also
e.g. Home Assistant, with an API token) sends commands with POST /devices/{id}/commands; they
reach the device over its event stream, and its next state report shows the result.

It is a remote control only: each device plays its own queue, several can play at the same
time, and controlling one does not stop the controller's own playback. Controlling is opt-in
(PUT/DELETE …/control), so the device can show who is steering it.

Nothing is stored. A device lives as long as its event connection, plus a short grace period
so a reconnect (EventSource retries after 3 s) does not drop it.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from audium.api.deps import current_user
from audium.api.eventbus import DeviceMessage, EventBus
from audium.errors import NotFound
from audium.services.users import User

router = APIRouter(tags=["devices"])

ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"
GRACE_S = 20.0
MAX_QUEUE_WINDOW = 400
KINDS = ("desktop", "phone", "tablet", "other")


def clean_name(name: str | None) -> str:
    return " ".join((name or "").split())[:60] or "audium"  # the web UI always sends a name


@dataclass(eq=False)
class Device:
    id: str
    user_id: int
    name: str
    kind: str
    since: float
    connections: int = 0
    status: dict[str, Any] | None = None
    queue: dict[str, Any] | None = None
    controllers: dict[str, str] = field(default_factory=dict)  # controlling device id -> name
    removal: asyncio.TimerHandle | None = None

    def public(self, with_queue: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "online": self.connections > 0,
            "since": int(self.since * 1000),
            "status": self.status,
            "controllers": [{"id": k, "name": v} for k, v in self.controllers.items()],
        }
        if with_queue:
            out["queue"] = self.queue
        return out


class DeviceRegistry:
    """Lives on the event loop: only async endpoints and the event stream touch it."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._devices: dict[tuple[int, str], Device] = {}

    def _announce(self, d: Device) -> None:
        self._bus.publish(DeviceMessage(d.user_id, "device", d.public()))

    def get(self, user_id: int, device_id: str) -> Device | None:
        return self._devices.get((user_id, device_id))

    def list(self, user_id: int) -> list[Device]:
        return sorted((d for (uid, _), d in self._devices.items() if uid == user_id), key=lambda d: d.since)

    def connect(self, user_id: int, device_id: str, name: str | None, kind: str | None) -> Device:
        d = self._devices.get((user_id, device_id))
        if d is None:
            d = Device(device_id, user_id, clean_name(name), kind if kind in KINDS else "other", time.time())
            self._devices[(user_id, device_id)] = d
        else:
            d.name = clean_name(name) if name else d.name
        if d.removal:
            d.removal.cancel()
            d.removal = None
        d.connections += 1
        self._announce(d)
        return d

    def disconnect(self, user_id: int, device_id: str) -> None:
        d = self._devices.get((user_id, device_id))
        if d is None:
            return
        d.connections = max(0, d.connections - 1)
        if d.connections:
            return
        self._announce(d)  # offline for now; gone if it does not come back
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._remove(d)
            return
        d.removal = loop.call_later(GRACE_S, self._remove, d)

    def _remove(self, d: Device) -> None:
        if self._devices.get((d.user_id, d.id)) is not d or d.connections:
            return
        del self._devices[(d.user_id, d.id)]
        self._bus.publish(DeviceMessage(d.user_id, "device-gone", {"id": d.id}))
        # Whatever it was steering no longer is.
        for other in self.list(d.user_id):
            if other.controllers.pop(d.id, None) is not None:
                self._announce(other)

    def set_state(self, d: Device, status: dict[str, Any], queue: dict[str, Any] | None) -> None:
        d.status = status
        self._announce(d)
        if queue is not None:
            d.queue = queue
            self._bus.publish(DeviceMessage(d.user_id, "device-queue", {"id": d.id, "queue": queue}))

    def command(self, d: Device, action: str, args: dict[str, Any], sender: str | None) -> None:
        data = {"action": action, "args": args, "from": sender}
        self._bus.publish(DeviceMessage(d.user_id, "command", data, to=d.id))

    def rename(self, d: Device, name: str) -> None:
        d.name = clean_name(name)
        self._announce(d)
        for other in self.list(d.user_id):  # it may be steering others
            if d.id in other.controllers:
                other.controllers[d.id] = d.name
                self._announce(other)

    def set_controller(self, d: Device, controller_id: str, name: str | None, on: bool) -> None:
        if on:
            own = self.get(d.user_id, controller_id)
            d.controllers[controller_id] = own.name if own else clean_name(name)
        elif d.controllers.pop(controller_id, None) is None:
            return
        self._announce(d)


def registry(request: Request) -> DeviceRegistry:
    return request.app.state.devices


def _online(reg: DeviceRegistry, user: User, device_id: str) -> Device:
    d = reg.get(user.id, device_id)
    if d is None or not d.connections:
        raise NotFound("device not connected")
    return d


# --- models ------------------------------------------------------------------------------------


class DeviceStatus(BaseModel):
    playing: bool = False
    buffering: bool = False
    position: float = Field(0, ge=0, description="Seconds into the track when the report was sent")
    duration: float = Field(0, ge=0)
    volume: float = Field(1, ge=0, le=1)
    muted: bool = False
    error: str | None = Field(None, max_length=200)
    blocked: bool = Field(False, description="The browser wants a tap on the device before it plays")
    radio: bool = False
    shuffle: bool = False
    repeat: Literal["off", "all", "one"] = "off"
    pos: int = Field(0, ge=0, description="Position of the current track in the play order")
    length: int = Field(0, ge=0, description="Tracks in the queue")
    source: dict[str, Any] | None = None
    track: dict[str, Any] | None = None


class QueueWindow(BaseModel):
    """Part of the queue around the current track, in play order, starting at `offset`."""

    offset: int = Field(ge=0)
    tracks: list[dict[str, Any]] = Field(max_length=MAX_QUEUE_WINDOW)


class StateIn(BaseModel):
    status: DeviceStatus
    queue: QueueWindow | None = Field(None, description="Only when the queue changed")


Action = Literal[
    "toggle", "play", "pause", "next", "prev", "seek", "volume", "mute", "shuffle", "repeat",
    "jump", "remove", "play_tracks", "play_pool", "play_radio", "play_next", "append", "enqueue",
]  # fmt: skip


class CommandIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    action: Action
    args: dict[str, Any] = Field(default_factory=dict)
    sender: str | None = Field(None, alias="from", pattern=ID_PATTERN, description="The controlling device")


class DeviceRename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ControlIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sender: str = Field(alias="from", pattern=ID_PATTERN)
    name: str | None = Field(None, max_length=60, description="Shown on the device when the controller is no player")


# --- endpoints ---------------------------------------------------------------------------------


@router.get("/devices", summary="Your players that are open right now")
async def list_devices(user: User = Depends(current_user), reg: DeviceRegistry = Depends(registry)):
    return [d.public(with_queue=True) for d in reg.list(user.id)]


@router.patch("/devices/{device_id}", summary="Rename a device (it keeps the name and sends it when it connects)")
async def rename_device(
    device_id: str, body: DeviceRename, user: User = Depends(current_user), reg: DeviceRegistry = Depends(registry)
):
    d = reg.get(user.id, device_id)
    if d is None:
        raise NotFound("device not connected")
    reg.rename(d, body.name)
    return d.public()


@router.put("/devices/{device_id}/state", status_code=204, summary="A device reports what it plays")
async def put_state(
    device_id: str, body: StateIn, user: User = Depends(current_user), reg: DeviceRegistry = Depends(registry)
):
    d = reg.get(user.id, device_id)
    if d is None:
        raise NotFound("device not connected")
    reg.set_state(d, body.status.model_dump(), body.queue.model_dump() if body.queue else None)
    return Response(status_code=204)


@router.post("/devices/{device_id}/commands", status_code=202, summary="Send a device a command")
async def post_command(
    device_id: str, body: CommandIn, user: User = Depends(current_user), reg: DeviceRegistry = Depends(registry)
):
    reg.command(_online(reg, user, device_id), body.action, body.args, body.sender)
    return {"sent": True}


@router.put("/devices/{device_id}/control", summary="Start controlling a device")
async def start_control(
    device_id: str, body: ControlIn, user: User = Depends(current_user), reg: DeviceRegistry = Depends(registry)
):
    d = _online(reg, user, device_id)
    reg.set_controller(d, body.sender, body.name, True)
    return d.public(with_queue=True)


@router.delete("/devices/{device_id}/control/{controller_id}", status_code=204, summary="Stop controlling a device")
async def stop_control(
    device_id: str, controller_id: str, user: User = Depends(current_user), reg: DeviceRegistry = Depends(registry)
):
    d = reg.get(user.id, device_id)
    if d is not None:
        reg.set_controller(d, controller_id, None, False)
    return Response(status_code=204)
