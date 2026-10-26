"""Login and media access for the audium apps (bearer token, media tokens, CORS)."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from audium.auth.media import make_media_token, read_media_token
from audium.db.schema import covers, tracks
from audium.util import now_ms
from tests.conftest import ADMIN_PW, cover_bytes, tags

APP = "tauri://localhost"


def _app_login(bare, password=ADMIN_PW, device="Pixel"):
    return bare.post("/api/v1/auth/app-login", json={"username": "admin", "password": password, "device": device})


def test_app_login_gives_a_token_not_a_cookie(app, admin, admin_client):
    with TestClient(app) as bare:
        assert _app_login(bare, "wrong").status_code == 401
        r = _app_login(bare)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["username"] == "admin" and body["token"].startswith("aud_")
        assert "set-cookie" not in r.headers
        auth = {"Authorization": f"Bearer {body['token']}"}
        assert bare.get("/api/v1/auth/me", headers=auth).status_code == 200
        # listed with the other tokens, so it can be revoked in the settings
        assert "App: Pixel" in [t["name"] for t in admin_client.get("/api/v1/auth/tokens").json()]
        # logging out of the app revokes its token
        assert bare.post("/api/v1/auth/logout", headers=auth).status_code == 200
        assert bare.get("/api/v1/auth/me", headers=auth).status_code == 401


def test_media_tokens(app, admin, admin_client, library, db):
    library.add("A/01.mp3", tags("Song"))
    (library.root / "A/cover.jpg").write_bytes(cover_bytes())
    library.scan()
    with db.read() as conn:
        track_id = conn.execute(select(tracks.c.id)).scalar_one()
        digest = conn.execute(select(covers.c.hash)).scalar_one()
    stream, cover = f"/api/v1/tracks/{track_id}/stream", f"/api/v1/covers/{digest}/64"

    # the web UI has its cookie and gets no media token
    assert admin_client.get("/api/v1/auth/media-token").status_code == 403

    with TestClient(app) as bare:
        token = _app_login(bare).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        mt = bare.get("/api/v1/auth/media-token", headers=auth).json()
        assert mt["expires_at"] > now_ms()
        assert bare.get(stream).status_code == 401
        assert bare.get(stream, params={"mt": mt["token"]}).status_code == 200
        assert bare.get(cover, params={"mt": mt["token"]}).status_code == 200
        # only for media: the rest of the API ignores it
        assert bare.get("/api/v1/auth/me", params={"mt": mt["token"]}).status_code == 401

        tampered = mt["token"][:-2] + ("AA" if not mt["token"].endswith("AA") else "BB")
        assert bare.get(stream, params={"mt": tampered}).status_code == 401
        key = app.state.media_key
        token_id, created_at, user_id = read_media_token(key, mt["token"], now_ms())
        expired = make_media_token(key, token_id, created_at, user_id, now_ms() - 1)
        assert bare.get(stream, params={"mt": expired}).status_code == 401

        # dies with the app's token, also when a new token gets the freed id (SQLite reuses it)
        bare.post("/api/v1/auth/logout", headers=auth)
        assert bare.get(stream, params={"mt": mt["token"]}).status_code == 401
        new = _app_login(bare).json()["token"]
        new_mt = bare.get("/api/v1/auth/media-token", headers={"Authorization": f"Bearer {new}"}).json()["token"]
        assert new_mt.split(".")[0] == mt["token"].split(".")[0]  # same id again
        assert bare.get(stream, params={"mt": mt["token"]}).status_code == 401
        assert bare.get(stream, params={"mt": new_mt}).status_code == 200


def test_cors_only_for_the_apps_and_never_with_cookies(app, admin):
    with TestClient(app) as bare:
        pre = bare.options(
            "/api/v1/auth/app-login",
            headers={
                "Origin": APP,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert pre.status_code == 200
        assert pre.headers["access-control-allow-origin"] == APP
        assert "access-control-allow-credentials" not in pre.headers
        r = bare.post(
            "/api/v1/auth/app-login",
            json={"username": "admin", "password": ADMIN_PW},
            headers={"Origin": APP},
        )
        assert r.headers["access-control-allow-origin"] == APP
        assert bare.get("/api/health", headers={"Origin": APP}).json()["server"] == "audium"

        evil = bare.options(
            "/api/v1/auth/app-login",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in evil.headers
