from fastapi.testclient import TestClient

from audium.config import Settings
from audium.main import create_app
from audium.services import auth as auth_service
from tests.conftest import ADMIN_PW, USER_PW, create_user, login


def _fresh_setup_token(db, settings) -> str:
    with db.write() as conn:
        return auth_service.bootstrap(conn, settings)


# --- first-run setup -----------------------------------------------------------------------


def test_setup_requires_token_and_creates_admin(client, db, settings):
    assert client.get("/api/v1/setup").json() == {"needs_setup": True}
    token = _fresh_setup_token(db, settings)
    body = {"setup_token": "wrong", "username": "boss", "password": "long-password"}
    assert client.post("/api/v1/setup", json=body).status_code == 403

    r = client.post("/api/v1/setup", json={**body, "setup_token": token})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    assert client.get("/api/v1/auth/me").json()["username"] == "boss"  # logged in via cookie

    assert client.get("/api/v1/setup").json() == {"needs_setup": False}
    assert client.post("/api/v1/setup", json={**body, "setup_token": token}).status_code == 409


def test_setup_token_attempts_are_rate_limited(client, db, settings):
    token = _fresh_setup_token(db, settings)
    body = {"setup_token": "nope", "username": "boss", "password": "long-password"}
    for _ in range(settings.login_max_attempts):
        assert client.post("/api/v1/setup", json=body).status_code == 403
    r = client.post("/api/v1/setup", json={**body, "setup_token": token})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_admin_from_environment(tmp_path, db, settings):
    s = Settings(**{**settings.model_dump(), "admin_user": "envadmin", "admin_password": "env-password-1"})
    with TestClient(create_app(s, db), headers={"X-Requested-With": "t"}) as c:
        assert c.get("/api/v1/setup").json() == {"needs_setup": False}
        assert login(c, "envadmin", "env-password-1")["role"] == "admin"


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
    defaults = {"theme": "system", "stream_quality": "auto", "shortcuts": "on"}
    assert a.get("/api/v1/auth/me/settings").json() == defaults
    r = a.patch("/api/v1/auth/me/settings", json={"theme": "light"})
    assert r.json() == {**defaults, "theme": "light"}
    a.patch("/api/v1/auth/me/settings", json={"stream_quality": "low", "shortcuts": "off"})
    assert a.get("/api/v1/auth/me/settings").json() == {"theme": "light", "stream_quality": "low", "shortcuts": "off"}
    assert b.get("/api/v1/auth/me/settings").json()["theme"] == "system"
    assert a.patch("/api/v1/auth/me/settings", json={"theme": "pink"}).status_code == 422
