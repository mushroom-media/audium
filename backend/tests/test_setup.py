import os

import pytest
from sqlalchemy import func, select

from audium.analysis.tasks import AnalysisScheduler
from audium.config import Settings
from audium.db.schema import jobs, library_roots, tracks
from audium.db.state import get_state
from audium.scanner.tasks import ScanScheduler
from audium.services import auth as auth_service
from audium.services import setup as setup_service
from tests.conftest import ADMIN_PW, USER_PW, create_user, login, tags


def _count(db, table):
    with db.read() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def _probe(client, path):
    r = client.post("/api/v1/admin/setup/probe", json={"path": str(path)})
    assert r.status_code == 200, r.text
    return r.json()


# --- trial scan ----------------------------------------------------------------------------


def test_probe_reports_what_is_there_and_writes_nothing(admin_client, library, db):
    library.add("A/Album/01.flac", tags("One"))
    library.add("A/Album/02.mp3", tags("Two"))
    (library.root / "A/Album/cover.jpg").write_bytes(b"x")
    (library.root / "A/Album/notes.txt").write_text("x")

    p = _probe(admin_client, library.root)
    assert p["readable"] is True and p["complete"] is True
    assert p["audio_files"] == 2 and p["size_bytes"] > 0
    assert {f["ext"]: f["count"] for f in p["formats"]} == {"flac": 1, "mp3": 1}
    assert p["other_files"] == 1 and p["image_files"] == 1
    assert p["folders_with_music"] == 1 and p["folders_with_cover"] == 1
    assert len(p["samples"]) == 1  # one file per folder
    assert p["samples"][0]["tagged"] is True and p["samples"][0]["artist"] == "Artist"
    assert p["warnings"] == []
    assert _count(db, tracks) == 0 and _count(db, library_roots) == 0


def test_probe_warns_about_a_folder_without_music(admin_client, settings):
    folder = settings.music_dir / "photos"
    folder.mkdir()
    for i in range(30):
        (folder / f"{i}.jpg").write_bytes(b"x")
    assert _probe(admin_client, folder)["warnings"] == ["no_audio"]


def test_probe_warns_about_mostly_other_files(admin_client, library):
    library.add("01.flac", tags("One"))
    for i in range(30):
        (library.root / f"{i}.mkv").write_bytes(b"x")
    assert "mostly_other_files" in _probe(admin_client, library.root)["warnings"]


def test_probe_warns_about_files_without_tags(admin_client, library):
    library.add("01.flac", {})
    p = _probe(admin_client, library.root)
    assert p["samples"][0]["tagged"] is False
    assert "few_tags" in p["warnings"]


@pytest.mark.skipif(os.getuid() == 0, reason="root can read everything")
def test_probe_tells_who_may_not_read(admin_client, library):
    library.add("01.flac", tags("One"))
    library.root.chmod(0o000)
    try:
        p = _probe(admin_client, library.root)
    finally:
        library.root.chmod(0o755)
    assert p["readable"] is False and p["warnings"] == ["unreadable"]
    assert p["mode"] == "0" and p["owner"] and p["container_user"]


def test_probe_stops_at_its_limit(admin_client, library, monkeypatch):
    monkeypatch.setattr(setup_service, "_PROBE_MAX_FILES", 1)
    library.add("A/01.flac", tags("One"))
    library.add("B/01.flac", tags("Two"))
    p = _probe(admin_client, library.root)
    assert p["complete"] is False and p["audio_files"] == 1


def test_probe_stays_inside_the_music_folder(admin_client, settings, tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    (settings.music_dir / "link").symlink_to(outside)
    for path in (outside, settings.music_dir / "link", settings.music_dir / ".." / "secret"):
        assert admin_client.post("/api/v1/admin/setup/probe", json={"path": str(path)}).status_code == 400


def test_setup_endpoints_are_for_admins(client, make_client, db, settings):
    urls = [("GET", "", None), ("POST", "/probe", {"path": "x"}), ("POST", "/complete", {"roots": None})]
    create_user(db, "user", USER_PW)
    user = make_client()
    login(user, "user", USER_PW)
    for method, url, body in urls:
        assert client.request(method, f"/api/v1/admin/setup{url}", json=body).status_code == 401
        assert user.request(method, f"/api/v1/admin/setup{url}", json=body).status_code == 403
    assert get_state_of(db) == "pending"


def get_state_of(db):
    with db.read() as conn:
        return get_state(conn, auth_service.SETUP_STATE_KEY)


# --- what the dialog knows -----------------------------------------------------------------


MOUNTINFO = (
    "1 0 8:1 / / rw,relatime - overlay overlay rw\n"
    "2 1 8:2 /srv/my\\040music /music/main ro,relatime master:1 - ext4 /dev/sda rw\n"
    "3 1 0:9 / /music/nas rw shared:2 propagation:x - cifs //nas/music rw\n"
    "4 1 8:2 /var/lib/docker/volumes/" + "a" * 64 + "/_data /data rw - ext4 /dev/sda rw\n"
)


def test_mounts_are_read_from_mountinfo():
    mounts = {m.path: m for m in setup_service.parse_mounts(MOUNTINFO)}
    assert mounts["/music/main"].read_only is True and mounts["/music/main"].network is False
    assert mounts["/music/main"].root == "/srv/my music"
    assert mounts["/music/nas"].read_only is False and mounts["/music/nas"].network is True


def test_anonymous_volume_does_not_count_as_persistent(tmp_path):
    s = Settings(data_dir="/data", music_dir=tmp_path)
    assert setup_service.data_persistent(s, setup_service.parse_mounts(MOUNTINFO)) is False
    named = MOUNTINFO.replace("/var/lib/docker/volumes/" + "a" * 64 + "/_data", "/home/me/data")
    assert setup_service.data_persistent(s, setup_service.parse_mounts(named)) is True
    assert setup_service.data_persistent(s, None) is None


def test_setup_info_suggests_the_top_level_folders(admin_client, settings):
    (settings.music_dir / "main").mkdir()
    (settings.music_dir / "nas").mkdir()
    info = admin_client.get("/api/v1/admin/setup").json()
    assert info["pending"] is True
    assert info["candidates"] == [str(settings.music_dir / "main"), str(settings.music_dir / "nas")]
    assert info["roots"] == [] and info["proxy_not_trusted"] is False


def test_setup_info_notices_a_proxy_that_is_not_trusted(admin_client):
    r = admin_client.get("/api/v1/admin/setup", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.json()["proxy_not_trusted"] is True


# --- finishing, and the workers waiting for it -----------------------------------------------


def test_complete_adds_the_folders_and_starts_the_scan(admin_client, settings, db):
    chosen = settings.music_dir / "main"
    chosen.mkdir()
    (settings.music_dir / "other").mkdir()
    r = admin_client.post("/api/v1/admin/setup/complete", json={"roots": [str(chosen)]})
    assert r.status_code == 200, r.text
    assert r.json()["job_id"]
    assert [x["path"] for x in admin_client.get("/api/v1/admin/roots").json()] == [str(chosen)]
    assert get_state_of(db) == "done"
    # Asking again is fine: the dialog can be opened later.
    assert admin_client.post("/api/v1/admin/setup/complete", json={"roots": [str(chosen)]}).status_code == 200


def test_complete_changes_nothing_when_a_folder_is_refused(admin_client, settings, db):
    (settings.music_dir / "main").mkdir()
    r = admin_client.post("/api/v1/admin/setup/complete", json={"roots": [str(settings.music_dir / "main"), "/etc"]})
    assert r.status_code == 400
    assert _count(db, library_roots) == 0
    assert get_state_of(db) == "pending"


def _scan_jobs(db):
    with db.read() as conn:
        return conn.execute(select(func.count()).select_from(jobs).where(jobs.c.type == "scan")).scalar_one()


def test_scan_waits_for_the_dialog(client, admin, db, settings):
    (settings.music_dir / "main").mkdir()
    scheduler = ScanScheduler(db, settings)
    scheduler()
    assert _count(db, library_roots) == 0 and _scan_jobs(db) == 0

    login(client, "admin", ADMIN_PW)
    assert (
        client.post("/api/v1/admin/setup/complete", json={"roots": [str(settings.music_dir / "main")]}).status_code
        == 200
    )
    jobs_after_dialog = _scan_jobs(db)
    assert jobs_after_dialog == 1
    with db.write() as conn:
        conn.execute(jobs.update().values(status="done"))  # the scan has run
    scheduler()
    assert _scan_jobs(db) == jobs_after_dialog  # no second scan on top of the dialog's own


def test_skipping_the_dialog_finds_the_folders_as_before(client, admin, db, settings):
    (settings.music_dir / "main").mkdir()
    login(client, "admin", ADMIN_PW)
    assert client.post("/api/v1/admin/setup/complete", json={"roots": None}).json()["job_id"] is None
    ScanScheduler(db, settings)()
    assert _count(db, library_roots) == 1 and _scan_jobs(db) == 1


@pytest.mark.parametrize(
    "env", [{"admin_user": "boss", "admin_password": "long-password"}, {"library_roots": "/music/main"}]
)
def test_scan_does_not_wait_when_configured_through_the_environment(db, settings, env):
    s = Settings(**{**settings.model_dump(), **env})
    with db.write() as conn:
        auth_service.bootstrap(conn, s)
    ScanScheduler(db, s)()
    assert _scan_jobs(db) == 1


def test_analysis_and_its_download_wait_for_the_dialog(client, admin, db, settings):
    AnalysisScheduler(db, settings)()
    with db.read() as conn:
        assert conn.execute(select(func.count()).select_from(jobs)).scalar_one() == 0

    login(client, "admin", ADMIN_PW)
    client.post("/api/v1/admin/setup/complete", json={"roots": None})
    AnalysisScheduler(db, settings)()
    with db.read() as conn:
        assert conn.execute(select(func.count()).select_from(jobs)).scalar_one() > 0
