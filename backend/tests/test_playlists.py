import pytest
from sqlalchemy import select, update

from audium.api import events as events_module
from audium.db.schema import play_history, playlist_items, tracks
from audium.services import playlists as svc
from tests.conftest import USER_PW, cover_bytes, create_user, login, tags


@pytest.fixture
def world(library, db, make_client):
    """alice owns a playlist; bob is editor, carol viewer; dave and the admin have no share."""
    for i in range(1, 7):
        library.add(f"A/{i}.mp3", tags(f"Song {i}", track=i))
    library.scan()
    with db.read() as conn:
        track_ids = [r.id for r in conn.execute(select(tracks.c.id).order_by(tracks.c.track_no))]
    people = {}
    for name, role in [
        ("alice", "user"),
        ("bob", "user"),
        ("carol", "user"),
        ("dave", "user"),
        ("eve", "user"),
        ("root", "admin"),
    ]:
        user = create_user(db, name, USER_PW, role)
        c = make_client()
        login(c, name, USER_PW)
        people[name] = (user, c)
    alice = people["alice"][1]
    pl = alice.post("/api/v1/playlists", json={"name": "Road Trip", "track_ids": track_ids[:3]}).json()
    alice.put(f"/api/v1/playlists/{pl['id']}/shares/{people['bob'][0].id}", json={"role": "editor"})
    alice.put(f"/api/v1/playlists/{pl['id']}/shares/{people['carol'][0].id}", json={"role": "viewer"})
    return {"pl": pl["id"], "tracks": track_ids, "people": people}


def client_of(world, name):
    return world["people"][name][1]


def uid(world, name):
    return world["people"][name][0].id


def item_ids(world, name="alice"):
    r = client_of(world, name).get(f"/api/v1/playlists/{world['pl']}/items").json()
    return [i["item_id"] for i in r["items"]]


def titles(world, name="alice"):
    r = client_of(world, name).get(f"/api/v1/playlists/{world['pl']}/items").json()
    return [i["track"]["title"] for i in r["items"]]


# --- the permission matrix ------------------------------------------------------------------

ACTIONS = {
    "view": lambda c, w: c.get(f"/api/v1/playlists/{w['pl']}"),
    "items": lambda c, w: c.get(f"/api/v1/playlists/{w['pl']}/items"),
    "shares": lambda c, w: c.get(f"/api/v1/playlists/{w['pl']}/shares"),
    "add": lambda c, w: c.post(f"/api/v1/playlists/{w['pl']}/items", json={"track_ids": [w["tracks"][5]]}),
    "remove": lambda c, w: c.post(f"/api/v1/playlists/{w['pl']}/items/remove", json={"item_ids": item_ids(w)[:1]}),
    "move": lambda c, w: c.post(
        f"/api/v1/playlists/{w['pl']}/items/{item_ids(w)[2]}/move", json={"after_item_id": None}
    ),
    "rename": lambda c, w: c.patch(f"/api/v1/playlists/{w['pl']}", json={"name": "Hijacked"}),
    "visibility": lambda c, w: c.patch(f"/api/v1/playlists/{w['pl']}", json={"visibility": "users"}),
    "share": lambda c, w: c.put(f"/api/v1/playlists/{w['pl']}/shares/{uid(w, 'eve')}", json={"role": "editor"}),
    "unshare": lambda c, w: c.delete(f"/api/v1/playlists/{w['pl']}/shares/{uid(w, 'carol')}"),
    "delete": lambda c, w: c.delete(f"/api/v1/playlists/{w['pl']}"),
}
VIEW = {"view", "items", "shares"}
EDIT = {"add", "remove", "move"}
MANAGE = {"rename", "visibility", "share", "unshare", "delete"}

# who: (user name, whether the playlist is made visible to all users first)
WHO = {
    "owner": ("alice", False),
    "editor": ("bob", False),
    "viewer": ("carol", False),
    "public": ("dave", True),
    "stranger": ("dave", False),
    "admin": ("root", False),
}
ALLOWED = {
    "owner": VIEW | EDIT | MANAGE,
    "editor": VIEW | EDIT,
    "viewer": VIEW,
    "public": VIEW,
    "stranger": set(),
    "admin": set(),  # admins manage accounts, not other people's playlists
}


@pytest.mark.parametrize("who", list(WHO))
@pytest.mark.parametrize("action", list(ACTIONS))
def test_permission_matrix(world, who, action):
    name, public = WHO[who]
    if public:
        client_of(world, "alice").patch(f"/api/v1/playlists/{world['pl']}", json={"visibility": "users"})
    r = ACTIONS[action](client_of(world, name), world)
    if action in ALLOWED[who]:
        assert r.status_code in (200, 201), (who, action, r.text)
    elif who in ("stranger", "admin"):
        assert r.status_code == 404, (who, action, r.status_code)  # does not even reveal existence
    else:
        assert r.status_code == 403, (who, action, r.status_code)


def test_denied_writes_change_nothing(world):
    before = titles(world)
    for name in ("carol", "dave", "root"):
        ACTIONS["add"](client_of(world, name), world)
        ACTIONS["remove"](client_of(world, name), world)
        ACTIONS["rename"](client_of(world, name), world)
    assert titles(world) == before
    assert client_of(world, "alice").get(f"/api/v1/playlists/{world['pl']}").json()["name"] == "Road Trip"


def test_unauthenticated_gets_401(client, world):
    assert client.get(f"/api/v1/playlists/{world['pl']}").status_code == 401
    assert client.get("/api/v1/playlists").status_code == 401


# --- listing & roles ------------------------------------------------------------------------


def test_list_scopes_and_roles(world):
    def listing(name, scope="all"):
        return {
            p["name"]: p["role"]
            for p in client_of(world, name).get("/api/v1/playlists", params={"scope": scope}).json()
        }

    assert listing("alice") == {"Road Trip": "owner"}
    assert listing("bob") == {"Road Trip": "editor"}
    assert listing("bob", "shared") == {"Road Trip": "editor"}
    assert listing("bob", "mine") == {}
    assert listing("carol") == {"Road Trip": "viewer"}
    assert listing("dave") == {}
    assert listing("root") == {}
    client_of(world, "alice").patch(f"/api/v1/playlists/{world['pl']}", json={"visibility": "users"})
    assert listing("dave") == {"Road Trip": "viewer"}
    assert listing("dave", "public") == {"Road Trip": "viewer"}
    assert listing("bob", "public") == {}  # shared with bob already: shows under "shared"


def test_share_roles_can_change_and_be_left(world):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    alice.put(f"/api/v1/playlists/{world['pl']}/shares/{uid(world, 'bob')}", json={"role": "viewer"})
    assert ACTIONS["add"](bob, world).status_code == 403
    assert bob.post(f"/api/v1/playlists/{world['pl']}/leave").status_code == 200
    assert bob.get(f"/api/v1/playlists/{world['pl']}").status_code == 404
    shares = alice.get(f"/api/v1/playlists/{world['pl']}/shares").json()
    assert [s["user"]["username"] for s in shares] == ["carol"]
    assert (
        alice.put(f"/api/v1/playlists/{world['pl']}/shares/{uid(world, 'alice')}", json={"role": "editor"}).status_code
        == 400
    )
    assert alice.put(f"/api/v1/playlists/{world['pl']}/shares/99999", json={"role": "editor"}).status_code == 404
    assert alice.post(f"/api/v1/playlists/{world['pl']}/leave").status_code == 404  # owners cannot leave


def test_user_directory(world):
    names = [u["username"] for u in client_of(world, "alice").get("/api/v1/users").json()]
    assert "alice" not in names and {"bob", "carol", "dave"} <= set(names)


def test_deleted_user_shares_disappear(world, db):
    from audium.db.schema import users

    with db.write() as conn:
        conn.execute(users.delete().where(users.c.id == uid(world, "carol")))
    shares = client_of(world, "alice").get(f"/api/v1/playlists/{world['pl']}/shares").json()
    assert [s["user"]["username"] for s in shares] == ["bob"]


# --- ordering & concurrent editing ----------------------------------------------------------


def test_add_positions(world):
    alice = client_of(world, "alice")
    t = world["tracks"]
    first, second, _third = item_ids(world)
    alice.post(f"/api/v1/playlists/{world['pl']}/items", json={"track_ids": [t[3]], "position": "start"})
    alice.post(
        f"/api/v1/playlists/{world['pl']}/items",
        json={"track_ids": [t[4], t[5]], "position": "after", "after_item_id": first},
    )
    assert titles(world) == ["Song 4", "Song 1", "Song 5", "Song 6", "Song 2", "Song 3"]
    r = alice.post(f"/api/v1/playlists/{world['pl']}/items", json={"track_ids": [t[0]], "position": "after"})
    assert r.status_code == 400
    r = alice.post(f"/api/v1/playlists/{world['pl']}/items", json={"track_ids": [999999]})
    assert r.status_code == 400
    assert second in item_ids(world)


def test_two_editors_inserting_at_the_same_spot_both_win(world):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    anchor = item_ids(world)[0]
    t = world["tracks"]
    a = alice.post(
        f"/api/v1/playlists/{world['pl']}/items",
        json={"track_ids": [t[4]], "position": "after", "after_item_id": anchor},
    )
    b = bob.post(
        f"/api/v1/playlists/{world['pl']}/items",
        json={"track_ids": [t[5]], "position": "after", "after_item_id": anchor},
    )
    assert a.status_code == b.status_code == 200
    # The later insert lands directly after the anchor; nothing is lost or duplicated.
    assert titles(world) == ["Song 1", "Song 6", "Song 5", "Song 2", "Song 3"]
    assert titles(world, "bob") == titles(world, "alice")


def test_many_inserts_at_one_spot_trigger_renumbering(world, db):
    alice = client_of(world, "alice")
    anchor = item_ids(world)[0]
    t = world["tracks"]
    expected = ["Song 1"]
    for i in range(14):  # a 1024 gap is exhausted after ~10 bisections
        track = t[3 + i % 3]
        alice.post(
            f"/api/v1/playlists/{world['pl']}/items",
            json={"track_ids": [track], "position": "after", "after_item_id": anchor},
        )
        expected.insert(1, f"Song {4 + i % 3}")
    assert titles(world) == [*expected, "Song 2", "Song 3"]
    with db.read() as conn:
        positions = [
            r.position
            for r in conn.execute(
                select(playlist_items.c.position)
                .where(playlist_items.c.playlist_id == world["pl"])
                .order_by(playlist_items.c.position)
            )
        ]
    assert len(set(positions)) == len(positions)


def test_move(world):
    bob = client_of(world, "bob")
    first, second, third = item_ids(world)
    assert (
        bob.post(f"/api/v1/playlists/{world['pl']}/items/{third}/move", json={"after_item_id": None}).status_code == 200
    )
    assert titles(world) == ["Song 3", "Song 1", "Song 2"]
    bob.post(f"/api/v1/playlists/{world['pl']}/items/{third}/move", json={"after_item_id": second})
    assert titles(world) == ["Song 1", "Song 2", "Song 3"]
    bob.post(f"/api/v1/playlists/{world['pl']}/items/{first}/move", json={"after_item_id": third})
    assert titles(world) == ["Song 2", "Song 3", "Song 1"]
    assert (
        bob.post(f"/api/v1/playlists/{world['pl']}/items/{first}/move", json={"after_item_id": first}).status_code
        == 400
    )
    assert (
        bob.post(f"/api/v1/playlists/{world['pl']}/items/999999/move", json={"after_item_id": None}).status_code == 404
    )


def test_remove_is_idempotent_and_updates_stats(world):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    target = item_ids(world)[1]
    for c in (alice, bob):  # both remove the same item at once
        assert c.post(f"/api/v1/playlists/{world['pl']}/items/remove", json={"item_ids": [target]}).status_code == 200
    pl = alice.get(f"/api/v1/playlists/{world['pl']}").json()
    assert pl["item_count"] == 2
    assert titles(world) == ["Song 1", "Song 3"]


def test_if_match_detects_concurrent_changes(world):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    version = alice.get(f"/api/v1/playlists/{world['pl']}").json()["version"]
    bob.post(f"/api/v1/playlists/{world['pl']}/items", json={"track_ids": [world["tracks"][4]]})
    r = alice.post(
        f"/api/v1/playlists/{world['pl']}/items",
        json={"track_ids": [world["tracks"][5]]},
        headers={"If-Match": str(version)},
    )
    assert r.status_code == 409
    assert r.json()["error"]["version"] == version + 1
    r = alice.post(
        f"/api/v1/playlists/{world['pl']}/items",
        json={"track_ids": [world["tracks"][5]]},
        headers={"If-Match": str(version + 1)},
    )
    assert r.status_code == 200 and r.json()["version"] == version + 2


def test_versions_and_cached_stats(world):
    alice = client_of(world, "alice")
    pl = alice.get(f"/api/v1/playlists/{world['pl']}").json()
    assert pl["item_count"] == 3 and pl["duration_ms"] > 0 and pl["owner"]["username"] == "alice"
    v = pl["version"]
    alice.patch(f"/api/v1/playlists/{world['pl']}", json={"name": "  Road   Trip 2 "})
    pl = alice.get(f"/api/v1/playlists/{world['pl']}").json()
    assert pl["name"] == "Road Trip 2" and pl["version"] == v + 1
    assert alice.patch(f"/api/v1/playlists/{world['pl']}", json={"name": "   "}).status_code == 400


def test_filled_playlist_keeps_its_filters_and_can_be_filled_anew(world):
    alice = client_of(world, "alice")
    rule = {"match": "all", "conditions": [{"field": "year", "op": ">=", "value": 1990}], "limit": 3, "order": "random"}
    pl = alice.post("/api/v1/playlists", json={"name": "Filled", "track_ids": world["tracks"][:2], "fill_rule": rule})
    pl = pl.json()
    # Still an ordinary playlist: the filters are kept for editing, not as a smart rule.
    assert pl["kind"] == "manual" and pl["rule"] is None
    assert pl["fill_rule"]["conditions"] == rule["conditions"]
    assert pl["item_count"] == 2

    new_rule = {**rule, "conditions": [{"field": "year", "op": "<=", "value": 2030}]}
    r = alice.patch(f"/api/v1/playlists/{pl['id']}", json={"fill_rule": new_rule, "track_ids": world["tracks"][3:6]})
    assert r.status_code == 200
    out = r.json()
    assert out["fill_rule"]["conditions"] == new_rule["conditions"] and out["item_count"] == 3
    items = alice.get(f"/api/v1/playlists/{pl['id']}/items").json()["items"]
    assert [i["track"]["id"] for i in items] == world["tracks"][3:6]
    # Picked by the filters: marked as such. A track added by hand afterwards is not.
    assert all(i["auto"] for i in items)
    alice.post(f"/api/v1/playlists/{pl['id']}/items", json={"track_ids": world["tracks"][:1]})
    items = alice.get(f"/api/v1/playlists/{pl['id']}/items").json()["items"]
    assert [i["auto"] for i in items] == [True, True, True, False]

    # Only the owner, and never for smart playlists.
    bob = client_of(world, "bob")
    assert bob.patch(f"/api/v1/playlists/{world['pl']}", json={"track_ids": world["tracks"][:1]}).status_code == 403
    smart = alice.post("/api/v1/playlists", json={"name": "Smart", "rule": rule}).json()
    assert alice.patch(f"/api/v1/playlists/{smart['id']}", json={"track_ids": []}).status_code == 400
    # A plain playlist has no filters.
    assert alice.get(f"/api/v1/playlists/{world['pl']}").json()["fill_rule"] is None


def test_cover_preset_upload_and_reset(world, library):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    url = f"/api/v1/playlists/{world['pl']}/cover"
    upload = {"X-Requested-With": "audium", "Content-Type": "image/jpeg"}
    assert alice.get(f"/api/v1/playlists/{world['pl']}").json()["cover_source"] == "auto"

    pl = alice.put(url, json={"preset": 3}).json()
    assert (pl["cover_source"], pl["cover_preset"], pl["cover"]) == ("preset", 3, None)
    assert alice.put(url, json={"preset": 26}).status_code == 422
    assert bob.put(url, json={"preset": 1}).status_code == 403  # editors may not

    r = alice.post(url, content=cover_bytes(), headers=upload)
    assert r.status_code == 200
    pl = r.json()
    assert pl["cover_source"] == "upload" and pl["cover_preset"] is None and pl["cover"]
    assert alice.get(f"/api/v1/covers/{pl['cover']}/256").status_code == 200
    assert alice.post(url, content=b"not an image", headers=upload).status_code == 400
    assert bob.post(url, content=cover_bytes(), headers=upload).status_code == 403
    library.scan()  # the orphan cleanup keeps covers that playlists use
    assert alice.get(f"/api/v1/covers/{pl['cover']}/256").status_code == 200

    pl = alice.put(url, json={}).json()
    assert pl["cover_source"] == "auto" and pl["cover_preset"] is None


def test_missing_tracks_stay_but_are_marked_and_purge_cleans_up(world, db, library):
    (library.root / "A/2.mp3").unlink()
    library.scan()
    items = client_of(world, "alice").get(f"/api/v1/playlists/{world['pl']}/items").json()["items"]
    assert [i["available"] for i in items] == [True, False, True]
    with db.write() as conn:
        conn.execute(update(tracks).where(tracks.c.missing_since.is_not(None)).values(missing_since=1))
    library.scan()  # purge
    pl = client_of(world, "alice").get(f"/api/v1/playlists/{world['pl']}").json()
    assert pl["item_count"] == 2
    assert titles(world) == ["Song 1", "Song 3"]


# --- live updates ---------------------------------------------------------------------------


def test_event_recipients(world, db):
    alice = client_of(world, "alice")
    alice.post(f"/api/v1/playlists/{world['pl']}/items", json={"track_ids": [world["tracks"][4]]})
    with db.read() as conn:

        def seen_by(name):
            return [e.type for e in svc.events_since(conn, uid(world, name), 0)]

        assert "items" in seen_by("bob") and "items" in seen_by("carol")
        assert seen_by("dave") == [] and seen_by("root") == []
    # Removing carol's share is announced to carol too (so her client can drop it) ...
    alice.delete(f"/api/v1/playlists/{world['pl']}/shares/{uid(world, 'carol')}")
    with db.read() as conn:
        last = svc.events_since(conn, uid(world, "carol"), 0)[-1]
        assert last.type == "shares"
        # ... but later changes are not.
    alice.post(f"/api/v1/playlists/{world['pl']}/items", json={"track_ids": [world["tracks"][5]]})
    with db.read() as conn:
        assert svc.events_since(conn, uid(world, "carol"), last.seq) == []
    alice.patch(f"/api/v1/playlists/{world['pl']}", json={"visibility": "users"})
    with db.read() as conn:
        assert svc.events_since(conn, uid(world, "dave"), 0)[-1].type == "updated"


def _read_sse(client, last_event_id=None, max_events=20):
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    out = []
    with client.stream("GET", "/api/v1/events", headers=headers) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        block: dict = {}
        for line in r.iter_lines():
            if line.startswith(": keepalive"):
                break
            if not line:
                if block:
                    out.append(block)
                    block = {}
                if len(out) >= max_events:
                    break
                continue
            key, _, value = line.partition(": ")
            block[key] = value
    return out


def test_sse_replays_missed_events_per_user(world, monkeypatch):
    monkeypatch.setattr(events_module, "KEEPALIVE_S", 0.05)
    alice = client_of(world, "alice")
    alice.post(f"/api/v1/playlists/{world['pl']}/items", json={"track_ids": [world["tracks"][4]]})
    bob_events = [e for e in _read_sse(client_of(world, "bob"), last_event_id=0) if e.get("event") == "playlist"]
    assert bob_events and all(f'"playlist_id": {world["pl"]}' in e["data"] for e in bob_events)
    assert any('"type": "items"' in e["data"] for e in bob_events)
    seqs = [int(e["id"]) for e in bob_events]
    assert seqs == sorted(seqs)
    dave_events = [e for e in _read_sse(client_of(world, "dave"), last_event_id=0) if e.get("event") == "playlist"]
    assert dave_events == []
    hello = [e for e in _read_sse(client_of(world, "bob")) if "event" in e]  # fresh connection
    assert hello[0]["event"] == "hello" and int(hello[0]["id"]) >= max(seqs)


def test_event_bus_delivers_only_to_recipients():
    import asyncio

    from audium.api.eventbus import EventBus

    async def scenario():
        bus = EventBus()
        bus.bind(asyncio.get_running_loop())
        a, b = bus.subscribe(1), bus.subscribe(2)
        bus.publish(svc.Event(1, 5, "items", 2, 1, [1]), svc.Event(2, 6, "items", 1, 3, "*"), None)
        await asyncio.sleep(0.01)
        got_a = [a.queue.get_nowait().seq for _ in range(a.queue.qsize())]
        got_b = [b.queue.get_nowait().seq for _ in range(b.queue.qsize())]
        bus.unsubscribe(a)
        assert bus.subscriber_count == 1
        return got_a, got_b

    assert asyncio.run(scenario()) == ([1, 2], [2])


# --- favorites & history --------------------------------------------------------------------


def test_favorites_are_private(world):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    t = world["tracks"]
    for tid in (t[0], t[2], t[0]):  # adding twice is fine
        assert alice.put(f"/api/v1/favorites/track/{tid}").status_code == 200
    assert alice.put("/api/v1/favorites/track/999999").status_code == 404
    assert alice.put("/api/v1/favorites/song/1").status_code == 422
    assert alice.get("/api/v1/favorites/track/ids").json() == {"type": "track", "ids": [t[2], t[0]]}
    assert bob.get("/api/v1/favorites/track/ids").json()["ids"] == []
    page = alice.get("/api/v1/favorites/track").json()
    assert [i["title"] for i in page["items"]] == ["Song 3", "Song 1"] and page["total"] == 2
    album_id = page["items"][0]["album_id"]
    alice.put(f"/api/v1/favorites/album/{album_id}")
    assert alice.get("/api/v1/favorites/album").json()["items"][0]["id"] == album_id
    album_tracks = {tr["id"] for tr in alice.get(f"/api/v1/albums/{album_id}").json()["tracks"]}
    assert set(alice.get("/api/v1/tracks/ids", params={"favorite_albums": 1}).json()) == album_tracks
    assert bob.get("/api/v1/tracks/ids", params={"favorite_albums": 1}).json() == []
    alice.delete(f"/api/v1/favorites/track/{t[0]}")
    assert alice.get("/api/v1/favorites/track/ids").json()["ids"] == [t[2]]


def test_history(world):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    t = world["tracks"]
    for tid in (t[0], t[1], t[0]):
        assert alice.post("/api/v1/history", json={"track_id": tid, "played_ms": 30000}).status_code == 200
    assert alice.post("/api/v1/history", json={"track_id": 999999, "played_ms": 1}).status_code == 404
    hist = alice.get("/api/v1/history").json()
    assert [h["track"]["title"] for h in hist] == ["Song 1", "Song 2", "Song 1"]
    assert bob.get("/api/v1/history").json() == []
    albums = alice.get("/api/v1/history/albums").json()
    assert len(albums) == 1 and albums[0]["title"] == "Album"


def test_listening_stats(world, db):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    t = world["tracks"]
    for tid in (t[1], t[0], t[1], t[2], t[1], t[0]):
        assert alice.post("/api/v1/history", json={"track_id": tid, "played_ms": 30000}).status_code == 200
    lengths = {tid: alice.get(f"/api/v1/tracks/{tid}").json()["duration_ms"] for tid in t[:3]}

    s = alice.get("/api/v1/stats").json()
    assert s["since"] is None and s["plays"] == 6
    assert s["listening_ms"] == 3 * lengths[t[1]] + 2 * lengths[t[0]] + lengths[t[2]]
    assert [(e["track"]["id"], e["plays"]) for e in s["tracks"]] == [(t[1], 3), (t[0], 2), (t[2], 1)]
    assert [(e["album"]["title"], e["plays"]) for e in s["albums"]] == [("Album", 6)]
    assert s["artists"][0]["plays"] == 6 and s["artists"][0]["listening_ms"] == s["listening_ms"]
    assert s["tracks"][0]["listening_ms"] == 3 * lengths[t[1]]
    assert len(alice.get("/api/v1/stats", params={"limit": 1}).json()["tracks"]) == 1

    # a period that starts after the plays has none; other users see only their own
    later = alice.get("/api/v1/stats", params={"since": 2**50}).json()
    assert later["plays"] == 0 and later["listening_ms"] == 0 and later["tracks"] == []
    assert bob.get("/api/v1/stats").json()["plays"] == 0


def test_listening_time_is_what_really_sounded(world, db):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    t = world["tracks"]
    length = alice.get(f"/api/v1/tracks/{t[0]}").json()["duration_ms"]
    assert length > 600  # the test tracks are about a second long
    # reported, then skipped a little later: only what played counts, not the whole track
    r = alice.post("/api/v1/history", json={"track_id": t[0], "played_ms": 300, "listened_ms": 300})
    play = r.json()["id"]
    assert alice.post(f"/api/v1/history/{play}/listened", json={"listened_ms": 500}).status_code == 200
    # a late or repeated report never takes time away; nothing sounds longer than its track
    alice.post(f"/api/v1/history/{play}/listened", json={"listened_ms": 400})
    assert alice.get("/api/v1/stats").json()["listening_ms"] == 500
    other = alice.post("/api/v1/history", json={"track_id": t[0], "played_ms": 1, "listened_ms": 1}).json()["id"]
    alice.post(f"/api/v1/history/{other}/listened", json={"listened_ms": 86_000_000})
    s = alice.get("/api/v1/stats").json()
    assert s["plays"] == 2 and s["listening_ms"] == 500 + length
    assert s["tracks"][0]["listening_ms"] == s["artists"][0]["listening_ms"] == 500 + length
    # only your own plays; unknown ones are 404
    assert bob.post(f"/api/v1/history/{play}/listened", json={"listened_ms": 1}).status_code == 404
    assert alice.post("/api/v1/history/999999/listened", json={"listened_ms": 1}).status_code == 404
    # plays without a measurement (older ones, Subsonic apps) count with the track's length
    with db.write() as conn:
        conn.execute(update(play_history).where(play_history.c.id == play).values(listened_ms=None))
    assert alice.get("/api/v1/stats").json()["listening_ms"] == 2 * length


def test_recently_played_shows_sources(world):
    alice, bob = client_of(world, "alice"), client_of(world, "bob")
    t, pl = world["tracks"], world["pl"]

    def play(c, tid, context=None):
        r = c.post("/api/v1/history", json={"track_id": tid, "played_ms": 30000, "context": context})
        assert r.status_code == 200, r.text

    album_id = alice.get(f"/api/v1/tracks/{t[0]}").json()["album_id"]
    play(alice, t[1], f"radio:track:{t[0]}")
    play(alice, t[2], f"radio:track:{t[0]}")
    play(alice, t[0], f"playlist:{pl}")
    play(alice, t[3], "favorites")
    play(alice, t[4], f"album:{album_id}")
    recent = alice.get("/api/v1/history/recent").json()
    assert [(r["type"], r["id"], r["radio_of"]) for r in recent] == [
        ("album", album_id, None),
        ("favorites", None, None),
        ("playlist", pl, None),
        ("radio", t[0], "track"),
    ]
    assert recent[2]["name"] == "Road Trip" and recent[3]["name"] == "Song 1"
    assert alice.post("/api/v1/history", json={"track_id": t[0], "played_ms": 1, "context": "x:1"}).status_code == 422

    # a track played on its own (search, shuffled favorite albums) has no source and is left out
    play(bob, t[0])
    assert bob.get("/api/v1/history/recent").json() == []

    # a playlist bob can no longer see disappears from his list
    play(bob, t[0], f"playlist:{pl}")
    assert [r["type"] for r in bob.get("/api/v1/history/recent").json()] == ["playlist"]
    alice.delete(f"/api/v1/playlists/{pl}/shares/{uid(world, 'bob')}")
    assert bob.get("/api/v1/history/recent").json() == []


def test_playlist_cascade_when_owner_is_deleted(world, db):
    from audium.db.schema import playlists, users

    with db.write() as conn:
        conn.execute(users.delete().where(users.c.id == uid(world, "alice")))
        assert conn.execute(select(playlists)).all() == []
