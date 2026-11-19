import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, select, update

from audium.analysis import autoplaylists, genre_covers
from audium.api.subsonic import ids
from audium.db.schema import auto_playlist_covers, auto_playlists, covers, tracks
from audium.devtools.gen_testlib import generate_db
from audium.scanner.covers import CoverStore
from tests.test_subsonic import Sub, new_app_password


@pytest.fixture
def store(settings):
    return CoverStore(settings.covers_dir)


@pytest.fixture
def generated(settings, db, store):
    """A synthetic library (genres, album covers) with its auto-playlists and genre covers."""
    generate_db(settings, 600, seed=11)
    autoplaylists.generate_in(db, store)
    return db


def _genre_rows(db):
    with db.read() as conn:
        return {
            r.key: r
            for r in conn.execute(select(auto_playlists))
            if genre_covers.is_genre_key(r.key) and r.status != "dismissed"
        }


def test_render_is_a_blurred_square_with_a_gradient():
    red = Image.new("RGB", (256, 256), (200, 30, 30))
    blue = Image.new("RGB", (256, 256), (30, 30, 200))
    img = Image.open(io.BytesIO(genre_covers.render("genre:rock", [red, blue, red, blue])))
    assert img.size == (genre_covers.SIZE, genre_covers.SIZE)
    # Blurred: the hard edge between the tiles is gone.
    edge = [img.getpixel((x, 150)) for x in range(290, 311)]
    assert all(abs(a[0] - b[0]) < 12 for a, b in zip(edge, edge[1:], strict=False))
    # The gradient: one side is clearly darker than the opposite one.
    corners = [sum(img.getpixel(p)) for p in ((20, 20), (580, 20), (20, 580), (580, 580))]
    assert max(corners) - min(corners) > 60
    # The same albums still give each playlist a cover of its own.
    assert genre_covers.render("genre:rock", [red]) != genre_covers.render("family:rock", [red])
    # Without any album cover: the key's own colours, the same every time.
    plain = genre_covers.render("genre:jazz", [])
    assert plain == genre_covers.render("genre:jazz", [])
    assert plain != genre_covers.render("genre:blues", [])


def test_every_genre_playlist_gets_its_own_stored_cover(generated, store):
    rows = _genre_rows(generated)
    assert any(k.startswith("family:") for k in rows) and any(k.startswith("genre:") for k in rows)
    with generated.read() as conn:
        saved = dict(conn.execute(select(auto_playlist_covers.c.key, auto_playlist_covers.c.hash)).all())
        album_covers = set(conn.execute(select(covers.c.hash)).scalars())
        others = conn.execute(select(auto_playlists).where(auto_playlists.c.key.like("decade:%"))).all()
    assert set(saved) == set(rows)
    for key, row in rows.items():
        assert row.cover_hash == saved[key]
        assert store.exists(row.cover_hash)
        assert row.cover_hash not in album_covers  # made, not borrowed from a track
    assert len(set(saved.values())) == len(saved)  # one per playlist
    # Other auto-playlists keep the cover of their first track.
    assert others and all(r.cover_hash in album_covers | {None} for r in others)


def test_genre_cover_stays_when_the_playlist_changes(generated, store):
    before = {k: r.cover_hash for k, r in _genre_rows(generated).items()}
    key = next(k for k in before if k.startswith("genre:"))
    with generated.write() as conn:
        # Other tracks lead the playlist now, and it even goes away and comes back.
        conn.execute(update(tracks).values(cover_id=None))
        conn.execute(delete(auto_playlists).where(auto_playlists.c.key == key))
    stats = autoplaylists.generate_in(generated, store)
    after = {k: r.cover_hash for k, r in _genre_rows(generated).items()}
    assert after == before
    assert stats["covers"] == 0


def test_a_missing_cover_file_is_made_again(generated, store):
    rows = _genre_rows(generated)
    key = next(iter(rows))
    store.delete(rows[key].cover_hash)
    with generated.write() as conn:
        assert autoplaylists.generate(conn, store)["covers"] == 1
        new = conn.execute(select(auto_playlists.c.cover_hash).where(auto_playlists.c.key == key)).scalar_one()
        saved = genre_covers.stored(conn, key)
    assert new == saved and store.exists(new)


def test_without_album_covers_the_cover_is_a_gradient(generated, store, db):
    rows = _genre_rows(generated)
    key = next(iter(rows))
    with db.write() as conn:
        conn.execute(delete(auto_playlist_covers).where(auto_playlist_covers.c.key == key))
        conn.execute(update(tracks).values(cover_id=None))
    autoplaylists.generate_in(db, store)
    digest = _genre_rows(db)[key].cover_hash
    assert digest != rows[key].cover_hash and store.exists(digest)


def test_api_and_subsonic_show_the_genre_cover(generated, admin_client, app, store):
    row = next(r for k, r in _genre_rows(generated).items() if k.startswith("family:"))
    assert admin_client.get(f"/api/v1/autoplaylists/{row.id}").json()["cover"] == row.cover_hash
    listed = {a["id"]: a["cover"] for a in admin_client.get("/api/v1/autoplaylists").json()}
    assert listed[row.id] == row.cover_hash
    assert admin_client.get(f"/api/v1/covers/{row.cover_hash}/256").status_code == 200
    sub = Sub(TestClient(app), "admin", new_app_password(admin_client)["password"])
    entry = next(p for p in sub.get("getPlaylists")["playlists"]["playlist"] if p["id"] == ids.make(ids.AUTO, row.id))
    assert entry["coverArt"] == ids.cover(row.cover_hash)
    r = sub.raw("getCoverArt", {"id": ids.make(ids.AUTO, row.id), "size": 256}, headers={"Accept": "image/webp"})
    assert r.status_code == 200 and r.content == store.path(row.cover_hash, 256).read_bytes()
