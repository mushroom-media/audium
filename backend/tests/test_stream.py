import threading

import pytest
from sqlalchemy import select, update

from audium.config import Settings
from audium.db.engine import Database
from audium.db.schema import tracks
from audium.main import create_app
from tests.conftest import tags


@pytest.fixture
def lib_client(library, admin_client):
    library.add("A/song.flac", tags("Flac Song"))
    library.add("A/song.wma", tags("Wma Song"), fmt="wma")
    library.scan()
    return admin_client


def _track_id(db, title):
    with db.read() as conn:
        return conn.execute(select(tracks.c.id).where(tracks.c.title == title)).scalar_one()


def test_raw_stream_supports_range(lib_client, db, library):
    tid = _track_id(db, "Flac Song")
    size = (library.root / "A/song.flac").stat().st_size
    full = lib_client.get(f"/api/v1/tracks/{tid}/stream")
    assert full.status_code == 200
    assert full.headers["content-type"] == "audio/flac"
    assert full.headers["accept-ranges"] == "bytes"
    assert len(full.content) == size
    part = lib_client.get(f"/api/v1/tracks/{tid}/stream", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 100-199/{size}"
    assert part.content == full.content[100:200]
    tail = lib_client.get(f"/api/v1/tracks/{tid}/stream", headers={"Range": "bytes=-10"})
    assert tail.content == full.content[-10:]


def test_stream_starts_past_the_queue_of_reads(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/queue.db", read_concurrency=1)
    db._read_gate.acquire()  # a long read, e.g. all ids of a big library
    try:
        waiting = threading.Thread(target=lambda: db.read().__enter__(), daemon=True)
        waiting.start()
        waiting.join(0.2)
        assert waiting.is_alive()  # an ordinary read waits for its turn
        with db.read(urgent=True) as conn:
            assert conn.exec_driver_sql("select 1").scalar() == 1
    finally:
        db._read_gate.release()
    waiting.join(2)


@pytest.mark.parametrize(
    ("fmt", "content_type", "magic"),
    [("opus", "audio/ogg", b"OggS"), ("mp3", "audio/mpeg", None), ("aac", "audio/aac", None)],
)
def test_transcode_formats(lib_client, db, fmt, content_type, magic):
    tid = _track_id(db, "Wma Song")  # WMA: no browser plays it natively
    r = lib_client.get(f"/api/v1/tracks/{tid}/stream", params={"format": fmt, "bitrate": 64})
    assert r.status_code == 200
    assert r.headers["content-type"] == content_type
    assert len(r.content) > 500
    if magic:
        assert r.content.startswith(magic)
    elif fmt == "aac":
        assert r.content[0] == 0xFF and r.content[1] & 0xF0 == 0xF0  # ADTS sync word
    float(r.headers["x-content-duration"])


def test_transcode_start_offset_shortens_output(lib_client, db):
    tid = _track_id(db, "Flac Song")
    whole = lib_client.get(f"/api/v1/tracks/{tid}/stream", params={"format": "mp3", "bitrate": 128}).content
    later = lib_client.get(f"/api/v1/tracks/{tid}/stream", params={"format": "mp3", "bitrate": 128, "t": 0.6}).content
    assert 0 < len(later) < len(whole) * 0.7


def test_stream_needs_login(client, library, db):
    library.add("A/x.mp3", tags("X"))
    library.scan()
    assert client.get(f"/api/v1/tracks/{_track_id(db, 'X')}/stream").status_code == 401


def test_stream_never_leaves_the_library_folder(lib_client, db, settings):
    secret = settings.music_dir / "secret.txt"
    secret.write_text("nope")
    tid = _track_id(db, "Flac Song")
    with db.write() as conn:
        conn.execute(update(tracks).where(tracks.c.id == tid).values(rel_path="../secret.txt"))
    assert lib_client.get(f"/api/v1/tracks/{tid}/stream").status_code == 404


def test_missing_file_is_404(lib_client, db, library):
    tid = _track_id(db, "Flac Song")
    (library.root / "A/song.flac").unlink()
    assert lib_client.get(f"/api/v1/tracks/{tid}/stream").status_code == 404
    assert lib_client.get("/api/v1/tracks/999999/stream").status_code == 404


def test_invalid_parameters(lib_client, db):
    tid = _track_id(db, "Flac Song")
    assert lib_client.get(f"/api/v1/tracks/{tid}/stream", params={"format": "flac"}).status_code == 422
    assert lib_client.get(f"/api/v1/tracks/{tid}/stream", params={"format": "mp3", "bitrate": 5}).status_code == 422


# --- SPA ------------------------------------------------------------------------------------


@pytest.fixture
def web_dir(tmp_path):
    d = tmp_path / "web"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><html><head><title>audium</title></head><body></body></html>")
    (d / "assets" / "app-abc123.js").write_text("console.log(1)")
    (d / "manifest.webmanifest").write_text("{}")
    return d


def _client(settings, db, web_dir, base_path=""):
    from fastapi.testclient import TestClient

    s = Settings(**{**settings.model_dump(), "web_dir": web_dir, "base_path": base_path})
    return TestClient(create_app(s, db))


def test_spa_routes_and_caching(settings, db, web_dir):
    with _client(settings, db, web_dir) as c:
        index = c.get("/")
        assert index.status_code == 200 and index.headers["cache-control"] == "no-cache"
        assert '<base href="/">' in index.text and "window.__AUDIUM__" in index.text
        deep = c.get("/albums/12")  # client-side route
        assert deep.text == index.text
        asset = c.get("/assets/app-abc123.js")
        assert "immutable" in asset.headers["cache-control"]
        assert c.get("/assets/app-old.js").status_code == 404
        assert c.get("/api/v1/nope").status_code == 404
        assert c.get("/api/v1/nope").json()["error"]["code"] == "not_found"
        assert c.get("/../../etc/passwd").text == index.text  # no traversal, just the app


def test_spa_under_base_path(settings, db, web_dir):
    with _client(settings, db, web_dir, "/music") as c:
        r = c.get("/music/albums")
        assert '<base href="/music/">' in r.text
        assert '"basePath": "/music"' in r.text
        assert c.get("/music/assets/app-abc123.js").status_code == 200


def test_spa_not_built(settings, db, tmp_path):
    with _client(settings, db, tmp_path / "missing") as c:
        r = c.get("/")
        assert r.status_code == 200 and "not built" in r.text
