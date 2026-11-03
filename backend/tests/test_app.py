from fastapi.testclient import TestClient

from audium.config import Settings
from audium.db.state import set_state
from audium.jobs.queue import worker_heartbeat_key
from audium.main import create_app
from audium.util import now_ms
from tests.conftest import ADMIN_PW, cover_bytes, tags


def test_health(client, db):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "ok"
    assert body["workers"]["scan"] == "down"
    with db.write() as conn:
        set_state(conn, worker_heartbeat_key("scan"), str(now_ms()))
    assert client.get("/api/health").json()["workers"]["scan"] == "ok"


def test_openapi_documents_the_api(client):
    spec = client.get("/api/openapi.json").json()
    for path in ("/api/v1/tracks", "/api/v1/search", "/api/v1/auth/login", "/api/v1/admin/roots"):
        assert path in spec["paths"]
    assert client.get("/api/docs").status_code == 200


def test_base_path_behind_reverse_proxy(settings, db, admin):
    s = Settings(**{**settings.model_dump(), "base_path": "/music-server/"})
    assert s.base_path == "/music-server"
    with TestClient(create_app(s, db), headers={"X-Requested-With": "t"}) as c:
        assert c.get("/music-server/api/health").status_code == 200
        assert c.get("/api/health").status_code == 404
        r = c.get("/", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"] == "/music-server/"
        r = c.post("/music-server/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
        assert r.status_code == 200
        assert "path=/music-server" in r.headers["set-cookie"].lower()
        assert c.get("/music-server/api/v1/auth/me").status_code == 200
        # CSRF protection also applies under the base path
        with TestClient(create_app(s, db)) as bare:
            assert bare.post("/music-server/api/v1/auth/logout").status_code == 403
        assert "/music-server/api/openapi.json" in c.get("/music-server/api/docs").text


def test_secure_cookie_behind_https_proxy(settings, db, admin):
    with TestClient(create_app(settings, db), base_url="https://music.example", headers={"X-Requested-With": "t"}) as c:
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
        assert "secure" in r.headers["set-cookie"].lower()


def test_error_format(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthorized", "message": "not logged in"}}


def test_read_gate_serializes_and_is_reentrant(settings):
    import threading
    import time

    from audium.db.engine import Database

    db = Database(settings.db_url, read_concurrency=1)
    active, peak, lock = [0], [0], threading.Lock()

    def reader():
        with db.read(), db.read():  # nested read in the same thread must not deadlock
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            with lock:
                active[0] -= 1

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert peak[0] == 1
    with db.write(), db.read():  # writes are not gated, a read inside a write still works
        pass
    db.dispose()


def test_lists_are_compressed_audio_and_covers_are_not(library, admin_client, settings):
    for i in range(40):
        library.add(f"A/{i}.mp3", tags(f"Song {i}"), picture=cover_bytes())
    library.scan()
    gzip = {"Accept-Encoding": "gzip"}
    body = admin_client.get("/api/v1/tracks", headers=gzip)
    assert body.headers["content-encoding"] == "gzip" and body.json()["total"] == 40
    track = body.json()["items"][0]
    stream = admin_client.get(f"/api/v1/tracks/{track['id']}/stream", headers={**gzip, "Range": "bytes=0-9"})
    assert stream.status_code == 206 and "content-encoding" not in stream.headers
    cover = admin_client.get(f"/api/v1/covers/{track['cover']}/64", headers=gzip)
    assert cover.status_code == 200 and "content-encoding" not in cover.headers


def test_cover_needs_a_session_and_an_existing_file(library, admin_client, client, settings):
    library.add("A/1.mp3", tags("Song"), picture=cover_bytes())
    library.scan()
    digest = admin_client.get("/api/v1/tracks").json()["items"][0]["cover"]
    url = f"/api/v1/covers/{digest}/64"
    for _ in range(2):  # the first by the normal way, the second by the shortcut
        got = admin_client.get(url)
        assert got.status_code == 200 and got.headers["content-type"] == "image/webp"
        assert got.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert admin_client.get(f"/api/v1/covers/{'0' * 32}/64").status_code == 404
    assert admin_client.get(f"/api/v1/covers/{digest}/65").status_code == 404
    client.cookies.clear()
    assert client.get(url).status_code == 401
    client.cookies.set("audium_session", "invalid")
    assert client.get(url).status_code == 401
