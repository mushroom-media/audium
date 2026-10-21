from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audium.config import Settings
from audium.db.engine import Database
from audium.db.migrate import migrate
from audium.devtools.audiofiles import make_cover, make_templates, write_file
from audium.main import create_app
from audium.scanner.covers import CoverStore
from audium.scanner.scan import Scanner
from audium.services import users as user_service

ADMIN_PW = "admin-password-1"
USER_PW = "user-password-1"


@pytest.fixture(scope="session", autouse=True)
def fast_password_hashing():
    """Production argon2 parameters cost ~0.3 s per hash; tests create many users."""
    from argon2 import PasswordHasher

    from audium.auth import passwords

    original = passwords._hasher
    passwords._hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    passwords._DUMMY_HASH = passwords._hasher.hash("audium-dummy-password")
    yield
    passwords._hasher = original


@pytest.fixture(scope="session")
def templates(tmp_path_factory) -> dict[str, Path]:
    return make_templates(tmp_path_factory.mktemp("templates"))


@pytest.fixture
def settings(tmp_path) -> Settings:
    (tmp_path / "data").mkdir()
    (tmp_path / "music").mkdir()
    return Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        log_format="console",
        scan_workers=1,  # in-process; test_scan_with_reader_processes covers the pool
        login_max_attempts=5,
    )


@pytest.fixture
def db(settings) -> Database:
    migrate(settings.db_url)
    database = Database(settings.db_url)
    yield database
    database.dispose()


@pytest.fixture
def app(settings, db):
    return create_app(settings, db)


@pytest.fixture
def client(app):
    with TestClient(app, headers={"X-Requested-With": "test"}) as c:
        yield c


@pytest.fixture
def make_client(app):
    """Extra independent clients (own cookie jar), e.g. one per user."""
    clients = []

    def factory():
        c = TestClient(app, headers={"X-Requested-With": "test"})
        c.__enter__()
        clients.append(c)
        return c

    yield factory
    for c in clients:
        c.__exit__(None, None, None)


def create_user(db, username, password, role="user"):
    with db.write() as conn:
        return user_service.create_user(conn, username, password, role=role)


def login(client, username, password):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(db):
    return create_user(db, "admin", ADMIN_PW, "admin")


@pytest.fixture
def admin_client(client, admin):
    login(client, "admin", ADMIN_PW)
    return client


class Library:
    """Builds a music folder with real tagged files and scans it."""

    def __init__(self, settings: Settings, db: Database, templates: dict[str, Path]) -> None:
        self.settings = settings
        self.db = db
        self.templates = templates
        self.root = settings.music_dir / "lib"
        self.root.mkdir(exist_ok=True)
        self.covers = CoverStore(settings.covers_dir)

    def add(self, rel_path: str, tags: dict | None = None, fmt: str | None = None, picture: bytes | None = None):
        fmt = fmt or rel_path.rsplit(".", 1)[-1]
        dest = self.root / rel_path
        write_file(self.templates[fmt], dest, fmt, tags, picture)
        return dest

    def ensure_root(self) -> int:
        from audium.services import roots

        with self.db.write() as conn:
            existing = [r for r in roots.list_roots(conn) if r.path == str(self.root.resolve())]
            if existing:
                return existing[0].id
            return roots.add_root(conn, self.settings, str(self.root)).id

    def scan(self, force: bool = False, ctx=None):
        self.ensure_root()
        return Scanner(self.db, self.settings, self.covers, ctx).run(force=force)


@pytest.fixture
def library(settings, db, templates) -> Library:
    return Library(settings, db, templates)


def tags(title, artist="Artist", album="Album", track=1, **extra) -> dict:
    return {"title": title, "artist": artist, "album": album, "track": track, **extra}


def cover_bytes(color=(200, 30, 30), size=600) -> bytes:
    return make_cover(color, size)
