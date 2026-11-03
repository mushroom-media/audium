from sqlalchemy import func, select, text

from audium.analysis.tasks import AnalysisScheduler
from audium.config import Settings
from audium.db.schema import api_tokens, jobs, library_roots, playlists, sessions, tracks, user_settings, users
from audium.db.state import LIBRARY_GENERATION, get_state, set_state
from audium.scanner.tasks import ScanScheduler
from audium.services import auth as auth_service
from audium.services import reset as reset_service
from tests.conftest import ADMIN_PW, USER_PW, create_user, login, tags


def _count(db, table):
    with db.read() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def _filled(client, library, db):
    """A set-up server: a scanned library, a playlist, a server setting, a finished dialog."""
    library.add("A/Album/01.flac", tags("One"))
    library.add("A/Album/02.mp3", tags("Two"))
    library.scan()
    with db.read() as conn:
        track_ids = [t for (t,) in conn.execute(select(tracks.c.id))]
    assert client.post("/api/v1/playlists", json={"name": "Mix", "track_ids": track_ids}).status_code == 201
    assert client.patch("/api/v1/admin/settings", json={"subsonic_api": "off"}).status_code == 200
    assert client.post("/api/v1/admin/setup/complete", json={"roots": None}).status_code == 200
    with db.write() as conn:
        assert not auth_service.setup_pending(conn)


def _reset(client, keep_users, password=ADMIN_PW):
    return client.post("/api/v1/admin/setup/reset", json={"password": password, "keep_users": keep_users})


def test_reset_keeps_the_accounts_and_opens_the_dialog(admin_client, library, db):
    create_user(db, "bob", USER_PW)
    _filled(admin_client, library, db)
    with db.read() as conn:
        generation = get_state(conn, LIBRARY_GENERATION)

    r = _reset(admin_client, keep_users=True)
    assert r.status_code == 200, r.text
    assert r.json() == {"needs_setup": False}

    for table in (tracks, library_roots, playlists, sessions, api_tokens):
        assert _count(db, table) == 0, table.name
    assert _count(db, users) == 2
    with db.read() as conn:
        assert conn.execute(text("SELECT count(*) FROM tracks_fts")).scalar_one() == 0
        assert get_state(conn, "settings.subsonic_api") is None
        assert get_state(conn, LIBRARY_GENERATION) != generation
        assert auth_service.setup_pending(conn)
    # Everyone is logged out; the admin logs in again and lands in the dialog.
    assert admin_client.get("/api/v1/auth/me").status_code == 401
    login(admin_client, "admin", ADMIN_PW)
    assert admin_client.get("/api/v1/setup").json()["dialog_pending"] is True


def test_reset_without_accounts_starts_like_a_new_installation(admin_client, library, db):
    create_user(db, "bob", USER_PW)
    _filled(admin_client, library, db)
    admin_client.app.state.setup_until = 0  # the time for the first admin has run out

    r = _reset(admin_client, keep_users=False)
    assert r.json() == {"needs_setup": True}
    assert _count(db, users) == 0 and _count(db, user_settings) == 0
    status = admin_client.get("/api/v1/setup").json()
    assert status["needs_setup"] is True and status["window_open"] is True
    r = admin_client.post("/api/v1/setup", json={"username": "neu", "password": "a-long-password"})
    assert r.status_code == 200, r.text


def _usernames(db):
    with db.read() as conn:
        return [u for (u,) in conn.execute(select(users.c.username).order_by(users.c.id))]


def test_reset_keeps_the_admin_from_the_environment(db, settings):
    env = Settings(**{**settings.model_dump(), "admin_user": "Boss", "admin_password": "x" * 12})
    admin = create_user(db, "admin", ADMIN_PW, "admin")
    create_user(db, "boss", "x" * 12, "user")
    with db.write() as conn:
        reset_service.reset_server(conn, env, admin, ADMIN_PW, keep_users=False)
        assert not auth_service.needs_setup(conn)
        assert auth_service.login(conn, env, "boss", "x" * 12, "ip", None)[0].is_admin
    assert _usernames(db) == ["boss"]


def test_reset_creates_the_admin_from_the_environment_again(db, settings):
    env = Settings(**{**settings.model_dump(), "admin_user": "boss", "admin_password": "x" * 12})
    admin = create_user(db, "admin", ADMIN_PW, "admin")
    with db.write() as conn:
        reset_service.reset_server(conn, env, admin, ADMIN_PW, keep_users=False)
    assert _usernames(db) == ["boss"]


def test_reset_needs_the_password_and_an_admin(admin_client, make_client, db):
    create_user(db, "bob", USER_PW)
    assert _reset(admin_client, keep_users=True, password="wrong").status_code == 403
    assert _count(db, sessions) == 1  # nothing happened

    bob = make_client()
    login(bob, "bob", USER_PW)
    assert _reset(bob, keep_users=False, password=USER_PW).status_code == 403


def test_reset_asks_a_running_job_to_stop(admin_client, db):
    with db.write() as conn:
        conn.execute(
            jobs.insert(),
            [
                {"queue": "scan", "type": "scan", "status": status, "created_at": 0, "run_after": 0}
                for status in ("running", "queued", "done")
            ],
        )
    assert _reset(admin_client, keep_users=True).status_code == 200
    with db.read() as conn:
        left = conn.execute(select(jobs.c.status, jobs.c.cancel_requested)).all()
    assert [tuple(r) for r in left] == [("running", True)]


def test_workers_wait_for_the_dialog_again_after_a_reset(admin_client, db, settings, monkeypatch):
    (settings.music_dir / "main").mkdir()
    assert admin_client.post("/api/v1/admin/setup/complete", json={"roots": None}).status_code == 200
    scan, analysis = ScanScheduler(db, settings), AnalysisScheduler(db, settings)
    scan(), analysis()
    assert _count(db, library_roots) == 1

    assert _reset(admin_client, keep_users=True).status_code == 200
    monkeypatch.setattr("audium.scanner.tasks._TICK_S", 0)
    monkeypatch.setattr("audium.analysis.tasks._RESUME_CHECK_S", 0)
    for _ in range(2):
        scan(), analysis()
    assert _count(db, library_roots) == 0 and _count(db, jobs) == 0  # held by the dialog

    login(admin_client, "admin", ADMIN_PW)
    assert admin_client.post("/api/v1/admin/setup/complete", json={"roots": None}).status_code == 200
    scan(), analysis()
    assert _count(db, library_roots) == 1


def test_reset_keeps_the_bookkeeping_of_the_workers(admin_client, db):
    with db.write() as conn:
        set_state(conn, "worker.scan.heartbeat", "1")
        set_state(conn, "radio.sources", "{}")
    assert _reset(admin_client, keep_users=True).status_code == 200
    with db.read() as conn:
        assert get_state(conn, "worker.scan.heartbeat") == "1"
        assert get_state(conn, "radio.sources") is None
