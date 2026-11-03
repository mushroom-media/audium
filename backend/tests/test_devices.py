"""Remote control between a user's players (api/devices.py)."""

import asyncio
import json
import time

import pytest

from audium.api import devices as devices_module
from audium.api import events as events_module
from audium.api.devices import DeviceRegistry
from audium.api.eventbus import EventBus

from .conftest import USER_PW, create_user, login

DESK = "desk-0000-aaaa"
PHONE = "phone-000-bbbb"


@pytest.fixture
def people(db, make_client):
    out = {}
    for name in ("alice", "bob"):
        user = create_user(db, name, USER_PW)
        c = make_client()
        login(c, name, USER_PW)
        out[name] = (user, c)
    return out


def drain(sub) -> list:
    return [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]


def test_registry_routes_messages_and_forgets_devices():
    async def scenario():
        bus = EventBus()
        bus.bind(asyncio.get_running_loop())
        reg = DeviceRegistry(bus)
        desk, phone, other_user = bus.subscribe(1, DESK), bus.subscribe(1, PHONE), bus.subscribe(2)
        d = reg.connect(1, DESK, "  Firefox   auf Windows ", "desktop")
        reg.connect(1, PHONE, "Handy", "phone")
        reg.set_controller(d, PHONE, None, True)
        reg.command(d, "next", {}, PHONE)
        await asyncio.sleep(0.01)
        got_desk, got_phone = drain(desk), drain(phone)
        assert drain(other_user) == []  # another user never sees them
        assert [m.event for m in got_desk].count("command") == 1
        assert "command" not in [m.event for m in got_phone]  # only the device itself
        assert got_phone[-1].data["controllers"] == [{"id": PHONE, "name": "Handy"}]
        assert d.name == "Firefox auf Windows"

        # A reconnect within the grace period keeps the device (and who controls it).
        reg.disconnect(1, DESK)
        reg.connect(1, DESK, None, None)
        assert reg.get(1, DESK) is d and d.connections == 1 and d.controllers

        # The controller goes away for good: the device is no longer controlled.
        devices_module.GRACE_S = 0.01
        reg.disconnect(1, PHONE)
        await asyncio.sleep(0.05)
        assert reg.get(1, PHONE) is None
        assert d.controllers == {}
        events = [m.event for m in drain(desk)]
        assert "device-gone" in events

    old = devices_module.GRACE_S
    try:
        asyncio.run(scenario())
    finally:
        devices_module.GRACE_S = old


def test_state_commands_and_control(app, people):
    alice, bob = people["alice"][1], people["bob"][1]
    uid = people["alice"][0].id
    assert alice.get("/api/v1/devices").json() == []
    assert alice.put(f"/api/v1/devices/{DESK}/state", json={"status": {}}).status_code == 404

    app.state.devices.connect(uid, DESK, "Desktop", "desktop")
    track = {"id": 1, "title": "Song", "artist": "A"}
    state = {
        "status": {"playing": True, "position": 12.5, "duration": 200, "pos": 3, "length": 10, "track": track},
        "queue": {"offset": 0, "tracks": [track] * 10},
    }
    assert alice.put(f"/api/v1/devices/{DESK}/state", json=state).status_code == 204
    [d] = alice.get("/api/v1/devices").json()
    assert d["id"] == DESK and d["online"] and d["status"]["position"] == 12.5 and d["status"]["repeat"] == "off"
    assert len(d["queue"]["tracks"]) == 10

    # A status report without the queue keeps the last one.
    alice.put(f"/api/v1/devices/{DESK}/state", json={"status": {"playing": False}})
    [d] = alice.get("/api/v1/devices").json()
    assert d["status"]["playing"] is False and len(d["queue"]["tracks"]) == 10

    assert (
        alice.post(
            f"/api/v1/devices/{DESK}/commands", json={"action": "seek", "args": {"s": 30}, "from": PHONE}
        ).status_code
        == 202
    )
    assert alice.post(f"/api/v1/devices/{DESK}/commands", json={"action": "explode"}).status_code == 422
    # Bob cannot see or steer Alice's devices.
    assert bob.get("/api/v1/devices").json() == []
    assert bob.post(f"/api/v1/devices/{DESK}/commands", json={"action": "pause"}).status_code == 404
    assert bob.put(f"/api/v1/devices/{DESK}/control", json={"from": PHONE}).status_code == 404

    r = alice.put(f"/api/v1/devices/{DESK}/control", json={"from": PHONE, "name": "Home Assistant"})
    assert r.status_code == 200 and r.json()["controllers"] == [{"id": PHONE, "name": "Home Assistant"}]
    assert alice.delete(f"/api/v1/devices/{DESK}/control/{PHONE}").status_code == 204
    assert alice.get("/api/v1/devices").json()[0]["controllers"] == []

    r = alice.patch(f"/api/v1/devices/{DESK}", json={"name": "  Wohnzimmer   PC "})
    assert r.status_code == 200 and r.json()["name"] == "Wohnzimmer PC"
    assert bob.patch(f"/api/v1/devices/{DESK}", json={"name": "Mine"}).status_code == 404
    assert alice.patch(f"/api/v1/devices/{DESK}", json={"name": ""}).status_code == 422

    too_long = {"status": {}, "queue": {"offset": 0, "tracks": [track] * (devices_module.MAX_QUEUE_WINDOW + 1)}}
    assert alice.put(f"/api/v1/devices/{DESK}/state", json=too_long).status_code == 422


def test_event_stream_registers_the_device(people, monkeypatch):
    monkeypatch.setattr(events_module, "KEEPALIVE_S", 0.05)
    alice = people["alice"][1]
    with alice.stream("GET", "/api/v1/events", params={"device": DESK, "name": "Firefox", "kind": "desktop"}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event: hello"):
                break
    # After the connection closed the device stays for the grace period, offline.
    deadline = time.time() + 2
    while time.time() < deadline:
        found = alice.get("/api/v1/devices").json()
        if found and not found[0]["online"]:
            break
        time.sleep(0.05)
    assert found[0]["name"] == "Firefox" and found[0]["kind"] == "desktop" and not found[0]["online"]
    assert alice.post(f"/api/v1/devices/{DESK}/commands", json={"action": "pause"}).status_code == 404
    assert alice.get("/api/v1/events", params={"device": "x"}).status_code == 422


def test_device_messages_are_formatted_without_id():
    from audium.api.eventbus import DeviceMessage

    text = events_module._format(DeviceMessage(1, "device-gone", {"id": DESK}))
    assert text == f"event: device-gone\ndata: {json.dumps({'id': DESK})}\n\n"
