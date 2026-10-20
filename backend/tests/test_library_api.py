import pytest

from audium.devtools.gen_testlib import generate_db
from audium.util import norm
from tests.conftest import cover_bytes, tags


@pytest.fixture
def big(settings, db, admin_client):
    """~1500 synthetic tracks written through the scanner's write path."""
    generate_db(settings, 1500, seed=3)
    return admin_client


def _walk(client, path, **params):
    items, cursor, pages = [], None, 0
    while True:
        r = client.get(path, params={**params, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        body = r.json()
        items += body["items"]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            return items, body["total"], pages


@pytest.mark.parametrize("sort", ["title", "added", "year"])
def test_track_cursor_walk_is_complete_and_ordered(big, sort):
    items, total, pages = _walk(big, "/api/v1/tracks", sort=sort, limit=200)
    assert total == 1500
    assert len(items) == 1500
    assert len({t["id"] for t in items}) == 1500
    assert pages == 8
    if sort == "title":
        keys = [(norm(t["title"]), t["id"]) for t in items]
        assert keys == sorted(keys)
    if sort == "year":
        years = [t["year"] or 0 for t in items]
        assert years == sorted(years, reverse=True)  # newest first by default


def test_offset_jump_matches_cursor_walk(big):
    walked, _, _ = _walk(big, "/api/v1/tracks", sort="title", limit=100)
    page = big.get("/api/v1/tracks", params={"sort": "title", "offset": 700, "limit": 100}).json()
    assert [t["id"] for t in page["items"]] == [t["id"] for t in walked[700:800]]
    # continuing from the jump with its cursor yields the following slice
    nxt = big.get("/api/v1/tracks", params={"sort": "title", "cursor": page["next_cursor"], "limit": 100}).json()
    assert [t["id"] for t in nxt["items"]] == [t["id"] for t in walked[800:900]]


def test_order_asc_desc_are_mirrors(big):
    asc, _, _ = _walk(big, "/api/v1/albums", sort="artist", order="asc", limit=150)
    desc, _, _ = _walk(big, "/api/v1/albums", sort="artist", order="desc", limit=150)
    assert [a["id"] for a in asc] == [a["id"] for a in reversed(desc)]


@pytest.mark.parametrize("path", ["/api/v1/albums", "/api/v1/artists"])
def test_album_and_artist_walks(big, path):
    items, total, _ = _walk(big, path, limit=100)
    assert len(items) == total > 0
    assert len({i["id"] for i in items}) == total


def test_bad_cursors_are_rejected(big):
    page = big.get("/api/v1/tracks", params={"sort": "title", "limit": 10}).json()
    assert big.get("/api/v1/tracks", params={"cursor": "garbage"}).status_code == 400
    r = big.get("/api/v1/tracks", params={"sort": "added", "cursor": page["next_cursor"]})
    assert r.status_code == 400  # cursor belongs to another sort
    assert big.get("/api/v1/tracks", params={"sort": "nope"}).status_code == 422
    assert big.get("/api/v1/tracks", params={"limit": 501}).status_code == 422


def test_filters(big):
    artist = big.get("/api/v1/artists", params={"limit": 1}).json()["items"][0]
    albums, total, _ = _walk(big, "/api/v1/albums", artist_id=artist["id"])
    assert total == artist["album_count"] == len(albums)
    assert all(a["artist_id"] == artist["id"] for a in albums)
    tracks, total, _ = _walk(big, "/api/v1/tracks", artist_id=artist["id"])
    assert total == artist["track_count"] == len(tracks)
    r = big.get("/api/v1/albums", params={"year_from": 1990, "year_to": 1999, "limit": 500}).json()
    assert r["items"] and all(1990 <= a["year"] <= 1999 for a in r["items"])


def test_album_detail_track_order(big):
    album = big.get("/api/v1/albums", params={"limit": 1}).json()["items"][0]
    detail = big.get(f"/api/v1/albums/{album['id']}").json()
    assert len(detail["tracks"]) == album["track_count"]
    order = [(t["disc_no"] or 0, t["track_no"] or 0) for t in detail["tracks"]]
    assert order == sorted(order)
    assert big.get("/api/v1/albums/999999").status_code == 404


def test_listing_requires_login(client):
    for path in ("/api/v1/tracks", "/api/v1/albums", "/api/v1/artists", "/api/v1/search?q=ab"):
        assert client.get(path).status_code == 401


# --- search ---------------------------------------------------------------------------------


@pytest.fixture
def small(library, admin_client):
    library.add("Bjork/Homogenic/01.flac", tags("Hunter", artist="Björk", album="Homogenic", albumartist="Björk"))
    library.add("Bjork/Homogenic/02.flac", tags("Jóga", artist="Björk", album="Homogenic", albumartist="Björk"))
    library.add(
        "ACDC/Highway/01.mp3",
        tags("Highway to Hell", artist="AC/DC", album="Highway to Hell"),
        picture=cover_bytes(),
    )
    library.scan()
    return admin_client


def test_search_prefix_and_diacritics(small):
    r = small.get("/api/v1/search", params={"q": "bjor"}).json()
    assert [a["name"] for a in r["artists"]] == ["Björk"]
    assert {t["title"] for t in r["tracks"]} == {"Hunter", "Jóga"}
    assert [a["title"] for a in r["albums"]] == ["Homogenic"]
    r = small.get("/api/v1/search", params={"q": "joga bj"}).json()
    assert [t["title"] for t in r["tracks"]] == ["Jóga"]
    r = small.get("/api/v1/search", params={"q": "ac dc high", "types": "track"}).json()
    assert [t["title"] for t in r["tracks"]] == ["Highway to Hell"]
    assert r["albums"] == [] and r["artists"] == []


@pytest.mark.parametrize("q", ['"', "a", "hun* OR x", "NEAR(a b)", "x" * 200, "-:^"])
def test_search_input_is_never_a_syntax_error(small, q):
    assert small.get("/api/v1/search", params={"q": q}).status_code == 200


def test_search_types_validation(small):
    assert small.get("/api/v1/search", params={"q": "ab", "types": "song"}).status_code == 400


def test_search_hides_missing_tracks(small, library):
    (library.root / "Bjork/Homogenic/02.flac").unlink()
    library.scan()
    r = small.get("/api/v1/search", params={"q": "joga"}).json()
    assert r["tracks"] == []


# --- covers & counts ------------------------------------------------------------------------


def test_cover_endpoint(small, app):
    track = small.get("/api/v1/search", params={"q": "highway", "types": "track"}).json()["tracks"][0]
    digest = track["cover"]
    assert digest
    r = small.get(f"/api/v1/covers/{digest}/256")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert "immutable" in r.headers["cache-control"]
    assert r.content[:4] == b"RIFF"
    assert small.get(f"/api/v1/covers/{digest}/100").status_code == 404
    assert small.get("/api/v1/covers/../../etc/passwd/64").status_code == 404
    assert small.get(f"/api/v1/covers/{'0' * 32}/64").status_code == 404


def test_total_count_follows_scans(small, library):
    assert small.get("/api/v1/tracks", params={"limit": 1}).json()["total"] == 3
    library.add("New/01.mp3", tags("Fresh"))
    library.scan()
    assert small.get("/api/v1/tracks", params={"limit": 1}).json()["total"] == 4


def test_track_detail(small):
    tid = small.get("/api/v1/search", params={"q": "hunter"}).json()["tracks"][0]["id"]
    d = small.get(f"/api/v1/tracks/{tid}").json()
    assert d["artists"] == [{"id": d["artist_id"], "name": "Björk"}]
    assert d["path"] == "Bjork/Homogenic/01.flac"
    assert d["codec"] == "flac"
    assert d["tag_status"] == "ok"


def test_admin_library_endpoints(small, library, settings):
    roots = small.get("/api/v1/admin/roots").json()
    assert len(roots) == 1 and roots[0]["status"] == "online"
    browse = small.get("/api/v1/admin/browse").json()
    assert browse["path"] == str(settings.music_dir.resolve())
    assert [f["name"] for f in browse["folders"]] == ["lib"]
    assert browse["folders"][0]["root_id"] == roots[0]["id"]
    assert small.get("/api/v1/admin/browse", params={"path": "/etc"}).status_code == 400
    (settings.music_dir / "other").mkdir()
    r = small.post("/api/v1/admin/roots", json={"path": str(settings.music_dir / "other")})
    assert r.status_code == 201
    job = small.post("/api/v1/admin/scan", json={}).json()
    assert job["status"] == "queued"
    again = small.post("/api/v1/admin/scan", json={}).json()
    assert again["id"] == job["id"]  # deduplicated while queued
    cancelled = small.post(f"/api/v1/admin/jobs/{job['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    stats = small.get("/api/v1/admin/stats").json()
    assert stats["tracks"] == 3 and stats["albums"] == 2


def _plan(conn, stmt) -> str:
    compiled = stmt.compile(conn, compile_kwargs={"literal_binds": True})
    return " | ".join(r[3] for r in conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled}"))


@pytest.mark.parametrize(
    ("sorts", "base"),
    [
        ("TRACK_SORTS", "tracks"),
        ("ALBUM_SORTS", "albums"),
    ],
)
def test_list_queries_use_an_index_for_ordering(big, db, sorts, base):
    """Regression guard: a full sort (TEMP B-TREE) of 100k rows per page made offset jumps
    take >300 ms. Every list order must come straight from a (partial) index."""
    from sqlalchemy import select

    from audium.db.schema import albums, tracks
    from audium.services import library as lib

    table = {"tracks": tracks, "albums": albums}[base]
    condition = tracks.c.missing_since.is_(None) if base == "tracks" else albums.c.track_count > 0
    with db.read() as conn:
        for sort in getattr(lib, sorts).values():
            for desc in (False, True):
                order = [c.desc() if desc else c.asc() for c in sort.columns]
                stmt = select(table.c.id).where(condition).order_by(*order).limit(101).offset(500)
                plan = _plan(conn, stmt)
                assert "TEMP B-TREE" not in plan, (sort.name, desc, plan)
                assert "USING" in plan and "INDEX" in plan, (sort.name, desc, plan)
