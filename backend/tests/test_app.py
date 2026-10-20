from fastapi.testclient import TestClient

from audium.config import Settings
from audium.db.state import set_state
from audium.jobs.queue import worker_heartbeat_key
from audium.main import create_app
from audium.util import now_ms
from tests.conftest import ADMIN_PW


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
