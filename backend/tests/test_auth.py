import sqlite3
import time

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from audium.config import Settings
from audium.db.schema import app_state, sessions, users
from audium.db.state import get_state
from audium.i18n import tr, user_language
from audium.main import create_app
from audium.services import auth as auth_service
from tests.conftest import ADMIN_PW, USER_PW, create_user, login

# --- first-run setup -----------------------------------------------------------------------


def test_setup_creates_admin_once(client):
    assert client.get("/api/v1/setup").json() == {
        "needs_setup": True,
        "window_open": True,
        "dialog_pending": True,
        "language": None,
    }
    body = {"username": "boss", "password": "long-password"}

    r = client.post("/api/v1/setup", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    assert client.get("/api/v1/auth/me").json()["username"] == "boss"  # logged in via cookie

    # The dialog goes on after the account, the account cannot be created twice.
    assert client.get("/api/v1/setup").json() == {
        "needs_setup": False,
        "window_open": False,
        "dialog_pending": True,
        "language": None,
    }
    assert client.post("/api/v1/setup", json=body).status_code == 409


def test_setup_closes_after_its_time(client, app):
    app.state.setup_until = time.monotonic() - 1
    assert client.get("/api/v1/setup").json()["window_open"] is False
    r = client.post("/api/v1/setup", json={"username": "boss", "password": "long-password"})
    assert r.status_code == 403
    assert client.get("/api/v1/setup").json()["needs_setup"] is True  # nobody got the account


def test_setup_wants_a_longer_password_for_the_admin(client):
    r = client.post("/api/v1/setup", json={"username": "boss", "password": "short"})
    assert r.status_code == 400
    assert client.get("/api/v1/setup").json()["needs_setup"] is True


def test_apps_are_told_to_set_up_the_server_first(client):
    r = client.post("/api/v1/auth/app-login", json={"username": "boss", "password": "long-password"})
    assert r.status_code == 409
    assert r.json()["error"]["message"] == "this server is not set up yet"


def test_admin_from_environment(tmp_path, db, settings):
    s = Settings(**{**settings.model_dump(), "admin_user": "envadmin", "admin_password": "env-password-1"})
    with TestClient(create_app(s, db), headers={"X-Requested-With": "t"}) as c:
        status = c.get("/api/v1/setup").json()
        assert status["needs_setup"] is False
        assert status["dialog_pending"] is True  # the dialog comes after the first login
        assert login(c, "envadmin", "env-password-1")["role"] == "admin"


def test_installation_from_before_the_dialog_never_sees_it(db, settings):
    create_user(db, "old", USER_PW, "admin")
    with db.write() as conn:
        conn.execute(app_state.insert().values(key="setup.token_hash", value="x", updated_at=0))
        assert auth_service.bootstrap(conn, settings) is False
        assert auth_service.setup_pending(conn) is False
        assert get_state(conn, "setup.token_hash") is None


def test_restart_in_the_middle_of_the_dialog_continues_it(db, settings):
    with db.write() as conn:
        assert auth_service.bootstrap(conn, settings) is True
    create_user(db, "boss", USER_PW, "admin")
    with db.write() as conn:
        assert auth_service.bootstrap(conn, settings) is False  # the restart for a new music folder
        assert auth_service.setup_pending(conn) is True


# --- login, sessions, CSRF -----------------------------------------------------------------


def test_login_logout_and_me(client, admin):
    assert client.get("/api/v1/auth/me").status_code == 401
    user = login(client, "ADMIN", ADMIN_PW)  # usernames are case-insensitive
    assert user["username"] == "admin"
    cookie = client.cookies.get("audium_session")
    assert cookie
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200
    client.cookies.set("audium_session", cookie)  # replaying the old cookie must not work
    assert client.get("/api/v1/auth/me").status_code == 401


def test_session_renewal_is_skipped_while_the_database_is_busy(client, admin, db, settings):
    # A long write elsewhere (scan, analysis) must not make requests wait 15 s and fail: the
    # frontend took that for a logout.
    login(client, "admin", ADMIN_PW)
    with db.write() as conn:
        conn.execute(update(sessions).values(last_seen_at=0))  # renewal due
    lock = sqlite3.connect(settings.data_dir / "audium.db", isolation_level=None)
    lock.execute("BEGIN IMMEDIATE")
    try:
        start = time.monotonic()
        assert client.get("/api/v1/auth/me").status_code == 200
        assert time.monotonic() - start < 5
    finally:
        lock.execute("ROLLBACK")
        lock.close()
    assert client.get("/api/v1/auth/me").status_code == 200  # renewed now
    with db.read() as conn:
        assert conn.execute(select(sessions.c.last_seen_at)).scalar_one() > 0


def test_session_cookie_flags(client, admin):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie


def test_csrf_blocks_requests_a_foreign_page_could_send(app, admin):
    form = "username=admin&password=" + ADMIN_PW
    with TestClient(app) as bare:  # no X-Requested-With
        # What a cross-site <form> or no-cors fetch can produce: blocked.
        for content_type in ("application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "text/plain"):
            r = bare.post("/api/v1/auth/login", content=form, headers={"Content-Type": content_type})
            assert r.status_code == 403, content_type
        # JSON needs a CORS preflight, which audium never grants: allowed (Swagger UI works).
        r = bare.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
        assert r.status_code == 200
        assert bare.post("/api/v1/auth/logout").status_code == 403  # bodyless POST: simple request
        assert bare.post("/api/v1/auth/logout", headers={"X-Requested-With": "x"}).status_code == 200
        login(bare, "admin", ADMIN_PW)
        assert bare.get("/api/v1/auth/me").status_code == 200  # reads need nothing


def test_no_cors_headers_for_foreign_origins(client, admin):
    r = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in r.headers


def test_wrong_password_same_error_as_unknown_user(client, admin):
    a = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"})
    b = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "wrong-pass"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_login_rate_limit_blocks_even_correct_password(client, admin, settings):
    for _ in range(settings.login_max_attempts):
        r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_successful_login_resets_user_counter(client, admin, settings):
    for _ in range(settings.login_max_attempts - 1):
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"})
    login(client, "admin", ADMIN_PW)
    for _ in range(settings.login_max_attempts - 1):
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "x" * 9}).status_code == 401


def test_change_password_logs_out_other_sessions(make_client, admin):
    a, b = make_client(), make_client()
    login(a, "admin", ADMIN_PW)
    login(b, "admin", ADMIN_PW)
    r = a.post("/api/v1/auth/me/password", json={"current_password": "bad-one-1", "new_password": "new-password-1"})
    assert r.status_code == 403
    r = a.post("/api/v1/auth/me/password", json={"current_password": ADMIN_PW, "new_password": "new-password-1"})
    assert r.status_code == 200
    assert a.get("/api/v1/auth/me").status_code == 200
    assert b.get("/api/v1/auth/me").status_code == 401
    login(b, "admin", "new-password-1")


def test_edit_own_profile(make_client, admin, db):
    create_user(db, "bob", USER_PW)
    a = make_client()
    login(a, "admin", ADMIN_PW)

    r = a.patch("/api/v1/auth/me", json={"display_name": "  Die Chefin ", "avatar_color": "teal"})
    assert r.status_code == 200, r.text
    assert (r.json()["display_name"], r.json()["avatar_color"]) == ("Die Chefin", "teal")
    assert a.patch("/api/v1/auth/me", json={"avatar_color": "plaid"}).status_code == 400
    assert a.patch("/api/v1/auth/me", json={"avatar_color": ""}).json()["avatar_color"] is None

    # A new username: taken or invalid ones are refused, the session stays, the old name no longer logs in.
    assert a.patch("/api/v1/auth/me", json={"username": "Bob"}).status_code == 409
    assert a.patch("/api/v1/auth/me", json={"username": "x"}).status_code == 400
    r = a.patch("/api/v1/auth/me", json={"username": "Chefin"})
    assert r.json()["username"] == "chefin"
    assert a.get("/api/v1/auth/me").json()["display_name"] == "Die Chefin"
    other = make_client()
    assert other.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW}).status_code == 401
    login(other, "chefin", ADMIN_PW)


def test_sessions_list_and_revoke(make_client, admin):
    a, b = make_client(), make_client()
    login(a, "admin", ADMIN_PW)
    login(b, "admin", ADMIN_PW)
    sessions = a.get("/api/v1/auth/sessions").json()
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["current"])
    assert a.delete(f"/api/v1/auth/sessions/{other['id']}").status_code == 200
    assert b.get("/api/v1/auth/me").status_code == 401


# --- API tokens ----------------------------------------------------------------------------


def test_api_token_auth(app, admin_client):
    created = admin_client.post("/api/v1/auth/tokens", json={"name": "phone"}).json()
    token = created["token"]
    assert token.startswith("aud_")
    with TestClient(app) as bare:
        headers = {"Authorization": f"Bearer {token}"}
        assert bare.get("/api/v1/auth/me", headers=headers).json()["username"] == "admin"
        # Bearer requests are not CSRF-prone: no custom header needed for writes.
        assert bare.post("/api/v1/auth/tokens", json={"name": "x"}, headers=headers).status_code == 200
        assert admin_client.delete(f"/api/v1/auth/tokens/{created['id']}").status_code == 200
        assert bare.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert bare.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_tokens_are_private_per_user(make_client, admin, db):
    create_user(db, "bob", USER_PW)
    a, b = make_client(), make_client()
    login(a, "admin", ADMIN_PW)
    login(b, "bob", USER_PW)
    token_id = a.post("/api/v1/auth/tokens", json={"name": "a"}).json()["id"]
    assert b.get("/api/v1/auth/tokens").json() == []
    assert b.delete(f"/api/v1/auth/tokens/{token_id}").status_code == 404


# --- admin user management & permissions ---------------------------------------------------


def test_admin_endpoints_need_admin(make_client, admin, db):
    create_user(db, "bob", USER_PW)
    anon, bob = make_client(), make_client()
    login(bob, "bob", USER_PW)
    for method, path in [
        ("get", "/api/v1/admin/users"),
        ("post", "/api/v1/admin/users"),
        ("patch", "/api/v1/admin/users/1"),
        ("get", "/api/v1/admin/invites"),
        ("post", "/api/v1/admin/invites"),
        ("get", "/api/v1/admin/roots"),
        ("post", "/api/v1/admin/roots"),
        ("get", "/api/v1/admin/browse"),
        ("post", "/api/v1/admin/scan"),
        ("get", "/api/v1/admin/jobs"),
        ("get", "/api/v1/admin/stats"),
    ]:
        kwargs = {"json": {}} if method in ("post", "patch") else {}
        assert getattr(anon, method)(path, **kwargs).status_code == 401, path
        assert getattr(bob, method)(path, **kwargs).status_code == 403, path


def test_admin_creates_and_disables_user(admin_client, make_client):
    r = admin_client.post("/api/v1/admin/users", json={"username": "Carol", "password": USER_PW})
    assert r.status_code == 201
    carol_id = r.json()["id"]
    assert r.json()["username"] == "carol"
    assert admin_client.post("/api/v1/admin/users", json={"username": "carol", "password": USER_PW}).status_code == 409
    assert admin_client.post("/api/v1/admin/users", json={"username": "c", "password": USER_PW}).status_code == 400
    assert admin_client.post("/api/v1/admin/users", json={"username": "dave", "password": "ab"}).status_code == 400

    carol = make_client()
    login(carol, "carol", USER_PW)
    token = carol.post("/api/v1/auth/tokens", json={"name": "t"}).json()["token"]
    r = admin_client.patch(f"/api/v1/admin/users/{carol_id}", json={"status": "disabled"})
    assert r.json()["status"] == "disabled"
    # Locked out immediately: session, API token and new logins.
    assert carol.get("/api/v1/auth/me").status_code == 401
    assert carol.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert carol.post("/api/v1/auth/login", json={"username": "carol", "password": USER_PW}).status_code == 401

    admin_client.patch(f"/api/v1/admin/users/{carol_id}", json={"status": "active", "password": "reset-pass-1"})
    login(carol, "carol", "reset-pass-1")


def test_admin_cannot_lock_out_everyone(admin_client, admin, db):
    assert admin_client.patch(f"/api/v1/admin/users/{admin.id}", json={"status": "disabled"}).status_code == 403
    assert admin_client.patch(f"/api/v1/admin/users/{admin.id}", json={"role": "user"}).status_code == 403
    second = create_user(db, "second", ADMIN_PW, "admin")
    assert admin_client.patch(f"/api/v1/admin/users/{second.id}", json={"role": "user"}).status_code == 200
    # `second` is a normal user now; admin stays the last admin and cannot be removed by anyone.
    with db.write() as conn:
        from audium.errors import Conflict
        from audium.services import users as user_service

        promoted = user_service.update_user(conn, admin, second.id, role="admin")
        try:
            user_service.update_user(conn, promoted, admin.id, role="user")
            user_service.update_user(conn, admin, promoted.id, status="disabled")
            raise AssertionError("removing the last admin must fail")
        except Conflict:
            pass


# --- invites -------------------------------------------------------------------------------


def test_invite_flow(admin_client, make_client):
    created = admin_client.post("/api/v1/admin/invites", json={"role": "user", "ttl_hours": 24}).json()
    token = created["token"]
    guest = make_client()
    assert guest.get(f"/api/v1/invites/{token}").json() == {"valid": True, "role": "user"}
    r = guest.post("/api/v1/auth/register", json={"invite_token": token, "username": "erin", "password": USER_PW})
    assert r.status_code == 200
    assert r.json()["role"] == "user"
    assert guest.get("/api/v1/auth/me").json()["username"] == "erin"
    # single use
    other = make_client()
    assert other.get(f"/api/v1/invites/{token}").status_code == 404
    r = other.post("/api/v1/auth/register", json={"invite_token": token, "username": "frank", "password": USER_PW})
    assert r.status_code == 404
    invites = admin_client.get("/api/v1/admin/invites").json()
    assert invites[0]["used_by"] is not None


def test_revoked_and_invalid_invites(admin_client, make_client):
    created = admin_client.post("/api/v1/admin/invites", json={}).json()
    assert admin_client.delete(f"/api/v1/admin/invites/{created['id']}").status_code == 200
    guest = make_client()
    assert guest.get(f"/api/v1/invites/{created['token']}").status_code == 404
    assert guest.get("/api/v1/invites/made-up").status_code == 404


def test_user_settings_are_per_user(make_client, admin, db):
    create_user(db, "bob", USER_PW)
    a, b = make_client(), make_client()
    login(a, "admin", ADMIN_PW)
    login(b, "bob", USER_PW)
    defaults = {
        "language": "server",
        "language_default": "de",
        "theme": "system",
        "stream_quality": "auto",
        "shortcuts": "on",
        "replay_gain": "off",
        "crossfade": "off",
        "crossfade_s": 5,
        "backdrop_motion": 50,
        "library_tab": "last",
        "track_sort": "title",
        "album_sort": "title",
        "artist_role": "album",
        "artist_images": "server",
        "artist_images_default": "on",
        "subsonic_api": "on",
    }
    assert a.get("/api/v1/auth/me/settings").json() == defaults
    r = a.patch("/api/v1/auth/me/settings", json={"theme": "light"})
    assert r.json() == {**defaults, "theme": "light"}
    changes = {
        "stream_quality": "low",
        "shortcuts": "off",
        "replay_gain": "album",
        "library_tab": "artists",
        "album_sort": "year",
        "crossfade": "on",
        "crossfade_s": 8,
        "backdrop_motion": 0,
    }
    a.patch("/api/v1/auth/me/settings", json=changes)
    assert a.get("/api/v1/auth/me/settings").json() == {**defaults, "theme": "light", **changes}
    assert b.get("/api/v1/auth/me/settings").json()["theme"] == "system"
    assert a.patch("/api/v1/auth/me/settings", json={"theme": "pink"}).status_code == 422
    assert a.patch("/api/v1/auth/me/settings", json={"crossfade_s": 13}).status_code == 422
    assert (
        a.patch("/api/v1/auth/me/settings", json={"artist_images_default": "off"}).json()["artist_images_default"]
        == "on"
    )


def test_language_of_the_server_and_of_each_user(make_client, admin, db):
    create_user(db, "bob", USER_PW)
    a, b, guest = make_client(), make_client(), make_client()
    login(a, "admin", ADMIN_PW)
    login(b, "bob", USER_PW)
    # Nobody chose yet: the login page follows the browser, everything else is German.
    assert guest.get("/api/v1/setup").json()["language"] is None
    assert b.get("/api/v1/auth/me/settings").json()["language_default"] == "de"

    assert a.patch("/api/v1/admin/settings", json={"language": "en"}).status_code == 200
    assert guest.get("/api/v1/setup").json()["language"] == "en"
    assert b.get("/api/v1/auth/me/settings").json()["language_default"] == "en"
    assert b.patch("/api/v1/admin/settings", json={"language": "de"}).status_code == 403

    # A user's own choice wins over the server language.
    assert b.patch("/api/v1/auth/me/settings", json={"language": "de"}).json()["language"] == "de"
    assert b.patch("/api/v1/auth/me/settings", json={"language": "fr"}).status_code == 422
    assert a.get("/api/v1/auth/me/settings").json()["language"] == "server"
    with db.read() as conn:
        assert user_language(conn, admin.id) == "en"
        assert (
            user_language(conn, conn.execute(select(users.c.id).where(users.c.username == "bob")).scalar_one()) == "de"
        )


def test_tr():
    assert tr("de", "Oft gehört") == "Oft gehört"
    assert tr("en", "Oft gehört") == "Played a lot"
    assert tr("en", "Die {d}er", d=90) == "The 90s"
    assert tr("en", "something new") == "something new"  # no translation: stays as it is
