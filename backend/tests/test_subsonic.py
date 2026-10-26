import hashlib
import os
import stat
import time
from xml.etree.ElementTree import fromstring

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

from audium import __version__
from audium.auth.secretbox import SecretBox, load_key
from audium.config import Settings
from audium.db.schema import (
    albums,
    app_passwords,
    artists,
    auto_playlist_items,
    auto_playlists,
    playlist_events,
    playlists,
    tracks,
)
from audium.main import create_app
from audium.services import playlists as playlist_service
from audium.services import users as user_service
from audium.util import now_ms
from tests.conftest import ADMIN_PW, USER_PW, cover_bytes, create_user, login, tags

NS = "{http://subsonic.org/restapi}"


def body(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()["subsonic-response"]


def ok(r) -> dict:
    resp = body(r)
    assert resp["status"] == "ok", resp
    return resp


def error_code(r) -> int:
    resp = body(r)
    assert resp["status"] == "failed", resp
    return resp["error"]["code"]


class Sub:
    """A Subsonic app: logs in with an app password on every request, like the real ones."""

    def __init__(self, client: TestClient, username: str, password: str, method: str = "token") -> None:
        self.client = client
        self.username = username
        self.password = password
        self.method = method

    def auth(self) -> dict:
        if self.method == "plain":
            return {"u": self.username, "p": self.password}
        salt = os.urandom(6).hex()
        return {"u": self.username, "t": hashlib.md5((self.password + salt).encode()).hexdigest(), "s": salt}

    def raw(self, name: str, params=None, **kw):
        query = [("f", "json"), ("v", "1.16.1"), ("c", "pytest"), *self.auth().items()]
        if isinstance(params, dict):
            params = list(params.items())
        return self.client.get(f"/rest/{name}", params=query + list(params or []), **kw)

    def get(self, name: str, params=None, **kw) -> dict:
        return ok(self.raw(name, params, **kw))

    def code(self, name: str, params=None) -> int:
        return error_code(self.raw(name, params))


def new_app_password(client: TestClient, name: str = "phone") -> dict:
    r = client.post("/api/v1/auth/app-passwords", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def alice_web(db, make_client):
    create_user(db, "alice", USER_PW)
    c = make_client()
    login(c, "alice", USER_PW)
    return c


@pytest.fixture
def alice(alice_web, app):
    pw = new_app_password(alice_web)["password"]
    return Sub(TestClient(app), "alice", pw)


# --- envelope and protocol basics ------------------------------------------------------------


def test_ping_json(alice):
    resp = alice.get("ping")
    assert resp == {
        "status": "ok",
        "version": "1.16.1",
        "type": "audium",
        "serverVersion": __version__,
        "openSubsonic": True,
    }


def test_ping_xml_is_the_default(alice):
    r = alice.client.get("/rest/ping.view", params={k: v for k, v in alice.auth().items()})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    root = fromstring(r.content)
    assert root.tag == NS + "subsonic-response"
    assert root.attrib["status"] == "ok" and root.attrib["openSubsonic"] == "true"


def test_extensions_need_no_login(client):
    resp = ok(client.get("/rest/getOpenSubsonicExtensions", params={"f": "json"}))
    names = {e["name"] for e in resp["openSubsonicExtensions"]}
    assert names == {"apiKeyAuthentication", "formPost", "transcodeOffset"}
    root = fromstring(client.get("/rest/getOpenSubsonicExtensions").content)
    ext = root.find(NS + "openSubsonicExtensions")
    assert ext.attrib["name"] and ext.find(NS + "versions").text == "1"


def test_license(alice):
    assert alice.get("getLicense.view")["license"] == {"valid": True}


def test_errors_are_http_200_with_failed_status(alice, client):
    assert alice.code("getAvatar") == 0  # unknown/unsupported endpoint
    root = fromstring(client.get("/rest/ping.view").content)  # no credentials, XML
    assert root.attrib["status"] == "failed"
    assert root.find(NS + "error").attrib["code"] == "10"
    r = alice.raw("ping", {"f": "jsonp", "callback": "x"})
    assert r.status_code == 200 and fromstring(r.content).attrib["status"] == "failed"


def test_form_post_without_csrf_header(app, alice):
    """Subsonic apps POST forms without X-Requested-With; the body wins over the query."""
    form = "&".join(f"{k}={v}" for k, v in {**alice.auth(), "f": "json", "c": "test"}.items())
    with TestClient(app) as bare:
        r = bare.post(
            "/rest/ping.view?f=xml", content=form, headers={"content-type": "application/x-www-form-urlencoded"}
        )
        assert body(r)["status"] == "ok"
        assert bare.post("/api/v1/auth/logout").status_code == 403  # the guard still protects /api


def test_under_base_path(settings, db, alice):
    s = Settings(**{**settings.model_dump(), "base_path": "/music-server"})
    with TestClient(create_app(s, db)) as c:
        r = c.get("/music-server/rest/ping", params={"f": "json", **alice.auth()})
        assert ok(r)["status"] == "ok"


def test_can_be_disabled(settings, db):
    s = Settings(**{**settings.model_dump(), "subsonic_enabled": False})
    with TestClient(create_app(s, db)) as c:
        assert c.get("/rest/ping.view").status_code == 404
        assert c.get("/rest").status_code == 404


def test_unsupported_lists_are_empty(alice):
    assert alice.get("getPodcasts")["podcasts"] == {}
    assert alice.get("getInternetRadioStations")["internetRadioStations"] == {}
    assert alice.get("getLyrics", {"artist": "a", "title": "b"})["lyrics"] == {}
    assert alice.code("setRating", {"id": "tr-1", "rating": 5}) == 0
    assert alice.code("createUser", {"username": "x"}) == 0


# --- authentication --------------------------------------------------------------------------


def test_token_plain_and_enc_auth(alice):
    alice.get("ping")  # token
    alice.method = "plain"
    alice.get("ping")
    hexed = "enc:" + alice.password.encode().hex()
    r = alice.client.get("/rest/ping", params={"f": "json", "u": "alice", "p": hexed})
    assert ok(r)
    r = alice.client.get("/rest/ping", params={"f": "json", "u": "ALICE", "p": alice.password})
    assert ok(r)  # user names are case-insensitive


def test_wrong_and_missing_credentials(alice, client):
    def code(**params):
        return error_code(client.get("/rest/ping", params={"f": "json", **params}))

    assert code(u="alice", p="wrong") == 40
    assert code(u="nobody", p=alice.password) == 40
    assert code(u="alice", p="enc:zz") == 40
    assert code(u="alice", t="abc") == 10  # token without salt
    assert code(u="alice") == 10
    assert code(p=alice.password) == 10


def test_login_password_and_session_cookie_are_not_accepted(alice_web, alice):
    """App passwords only: the login password is never sent to third-party apps."""
    r = alice_web.get("/rest/ping", params={"f": "json", "u": "alice", "p": USER_PW})
    assert error_code(r) == 40
    r = alice_web.get("/rest/ping", params={"f": "json"})  # logged in by cookie, no credentials
    assert error_code(r) == 10


def test_api_key_auth(alice_web, client):
    token = alice_web.post("/api/v1/auth/tokens", json={"name": "app"}).json()["token"]
    r = client.get("/rest/tokenInfo", params={"f": "json", "apiKey": token})
    assert ok(r)["tokenInfo"] == {"username": "alice"}
    assert error_code(client.get("/rest/ping", params={"f": "json", "apiKey": token, "u": "alice"})) == 43
    assert error_code(client.get("/rest/ping", params={"f": "json", "apiKey": "aud_nope"})) == 44


def test_disabled_user_and_revoked_password(alice, alice_web, db, admin):
    entry = alice_web.get("/api/v1/auth/app-passwords").json()[0]
    with db.write() as conn:
        user_service.update_user(conn, admin, entry_owner(db, "alice"), status="disabled")
    assert alice.code("ping") == 40
    with db.write() as conn:
        user_service.update_user(conn, admin, entry_owner(db, "alice"), status="active")
    alice.get("ping")  # app passwords survive a disable/enable
    alice_web = login_again(alice_web)
    assert alice_web.delete(f"/api/v1/auth/app-passwords/{entry['id']}").status_code == 200
    assert alice.code("ping") == 40  # revoked: immediately invalid


def entry_owner(db, username) -> int:
    with db.read() as conn:
        return user_service.find_by_username(conn, username).id


def login_again(c):
    login(c, "alice", USER_PW)
    return c


def test_rate_limit(alice, client, alice_web):
    for _ in range(5):  # settings.login_max_attempts in the tests
        error_code(client.get("/rest/ping", params={"f": "json", "u": "alice", "p": "wrong"}))
    assert alice.code("ping") == 40  # blocked, even with the right password
    # the web login has its own counter
    assert alice_web.post("/api/v1/auth/login", json={"username": "alice", "password": USER_PW}).status_code == 200


def test_usage_is_recorded(alice, alice_web):
    alice.get("ping")
    entry = alice_web.get("/api/v1/auth/app-passwords").json()[0]
    assert entry["last_used_at"] and entry["last_client"] == "pytest"


# --- app passwords ---------------------------------------------------------------------------


def test_app_password_api(alice_web, make_client, db):
    created = new_app_password(alice_web, "  Symfonium   Handy ")
    assert created["name"] == "Symfonium Handy"
    pw = created["password"]
    assert len(pw) == 29 and pw.count("-") == 5 and pw[:4] == created["prefix"]
    assert not set(pw.replace("-", "")) & set("ilo01")
    listed = alice_web.get("/api/v1/auth/app-passwords").json()
    assert [e["id"] for e in listed] == [created["id"]] and "password" not in listed[0]
    assert alice_web.post("/api/v1/auth/app-passwords", json={"name": "   "}).status_code == 400
    # nobody else can see or revoke it
    create_user(db, "bob", USER_PW)
    bob = make_client()
    login(bob, "bob", USER_PW)
    assert bob.get("/api/v1/auth/app-passwords").json() == []
    assert bob.delete(f"/api/v1/auth/app-passwords/{created['id']}").status_code == 404
    assert make_client().get("/api/v1/auth/app-passwords").status_code == 401


def test_app_passwords_are_encrypted_with_a_key_outside_the_db(alice_web, db, settings):
    pw = new_app_password(alice_web)["password"]
    with db.read() as conn:
        row = conn.execute(select(app_passwords)).one()
    assert pw.encode() not in row.secret_enc
    assert settings.secret_key_file.is_file()
    if os.name == "posix":
        assert stat.S_IMODE(settings.secret_key_file.stat().st_mode) == 0o600
    box = SecretBox(load_key(settings))
    assert box.open(row.secret_enc, f"app-password:{row.user_id}".encode()) == pw
    assert box.open(row.secret_enc, b"app-password:999") is None  # bound to its user
    other = SecretBox(load_key(Settings(**{**settings.model_dump(), "secret_key": "something else"})))
    assert other.open(row.secret_enc, f"app-password:{row.user_id}".encode()) is None


def test_secret_key_from_env_is_stable(settings):
    s = Settings(**{**settings.model_dump(), "secret_key": "my passphrase"})
    assert load_key(s) == load_key(s) and len(load_key(s)) == 32
    assert not s.secret_key_file.exists()  # nothing written when the key comes from the env
    assert load_key(settings) == load_key(settings)  # the file key is created once and reused


# --- the library ---------------------------------------------------------------------------


@pytest.fixture
def lib(library, db, alice):
    red, blue = cover_bytes((200, 30, 30)), cover_bytes((30, 30, 200))
    library.add(
        "Beatles/Abbey Road/01.flac",
        tags("Come Together", "The Beatles", "Abbey Road", 1, date="1969", genre="Rock", albumartist="The Beatles"),
        picture=red,
    )
    library.add(
        "Beatles/Abbey Road/02.flac",
        tags("Something", "The Beatles", "Abbey Road", 2, date="1969", genre="Rock", albumartist="The Beatles"),
        picture=red,
    )
    library.add(
        "Beatles/Help/01.mp3",
        tags("Help!", "The Beatles", "Help!", 1, date="1965", genre="Pop", albumartist="The Beatles"),
    )
    library.add(
        "Abba/Arrival/01.mp3",
        tags("Dancing Queen", "ABBA", "Arrival", 1, date="1976", genre="Pop", albumartist="ABBA"),
        picture=blue,
    )
    library.add(
        "Zappa/Hot Rats/01.wma",
        tags("Peaches En Regalia", "Frank Zappa", "Hot Rats", 1, date="1969", genre="Jazz", albumartist="Frank Zappa"),
        fmt="wma",
    )
    library.add(
        "Various/Hits/01.mp3",
        tags("1999", "Prince", "Hits", 1, date="1982", albumartist="Various Artists", compilation="1"),
    )
    library.scan()
    with db.read() as conn:
        t = {r.title: r.id for r in conn.execute(select(tracks.c.id, tracks.c.title))}
        al = {r.title: r.id for r in conn.execute(select(albums.c.id, albums.c.title))}
        ar = {r.name: r.id for r in conn.execute(select(artists.c.id, artists.c.name))}
    return {"t": t, "al": al, "ar": ar, "sub": alice}


def test_music_folders(lib):
    folders = lib["sub"].get("getMusicFolders")["musicFolders"]["musicFolder"]
    assert len(folders) == 1 and isinstance(folders[0]["id"], int) and folders[0]["name"] == "lib"


def test_artists_index(lib):
    resp = lib["sub"].get("getArtists")["artists"]
    assert "The" in resp["ignoredArticles"]
    index = {i["name"]: [a["name"] for a in i["artist"]] for i in resp["index"]}
    assert index["A"] == ["ABBA"]
    assert index["B"] == ["The Beatles"]  # sorted without the article
    assert "Prince" not in sum(index.values(), [])  # album artists only
    beatles = next(a for i in resp["index"] for a in i["artist"] if a["name"] == "The Beatles")
    assert beatles["id"] == f"ar-{lib['ar']['The Beatles']}" and beatles["albumCount"] == 2
    folder = lib["sub"].get("getMusicFolders")["musicFolders"]["musicFolder"][0]["id"]
    assert lib["sub"].get("getArtists", {"musicFolderId": folder})["artists"]["index"] == resp["index"]


def test_artist_album_song(lib):
    sub = lib["sub"]
    artist = sub.get("getArtist", {"id": f"ar-{lib['ar']['The Beatles']}"})["artist"]
    assert [a["name"] for a in artist["album"]] == ["Help!", "Abbey Road"]  # by year
    album = sub.get("getAlbum", {"id": f"al-{lib['al']['Abbey Road']}"})["album"]
    assert album["songCount"] == 2 and album["year"] == 1969 and album["genre"] == "Rock"
    assert album["artistId"] == artist["id"] and album["coverArt"].startswith("co-")
    assert album["created"].endswith("Z")
    first = album["song"][0]
    assert [s["title"] for s in album["song"]] == ["Come Together", "Something"]
    assert first["suffix"] == "flac" and first["contentType"] == "audio/flac"
    assert first["isDir"] is False and first["type"] == "music" and first["duration"] == 1
    assert first["parent"] == album["id"] and first["albumId"] == album["id"]
    assert first["path"] == "Beatles/Abbey Road/01.flac"
    assert first["genres"] == [{"name": "Rock"}] and "transcodedSuffix" not in first
    song = sub.get("getSong", {"id": first["id"]})["song"]
    assert song == first
    wma = sub.get("getSong", {"id": f"tr-{lib['t']['Peaches En Regalia']}"})["song"]
    assert wma["transcodedSuffix"] == "mp3" and wma["transcodedContentType"] == "audio/mpeg"


def test_xml_lists_and_attributes(lib):
    sub = lib["sub"]
    params = [*sub.auth().items(), ("id", f"al-{lib['al']['Abbey Road']}")]
    root = fromstring(sub.client.get("/rest/getAlbum", params=params).content)
    album = root.find(NS + "album")
    assert album.attrib["songCount"] == "2"
    songs = album.findall(NS + "song")
    assert [s.attrib["title"] for s in songs] == ["Come Together", "Something"]
    assert songs[0].attrib["isDir"] == "false"
    assert songs[0].find(NS + "genres").attrib["name"] == "Rock"


def test_ids(lib, db):
    sub = lib["sub"]
    assert sub.code("getAlbum", {"id": "xx-1"}) == 70
    assert sub.code("getAlbum", {"id": f"tr-{lib['t']['Something']}"}) == 70  # wrong kind
    assert sub.code("getAlbum", {"id": "al-abc"}) == 70
    assert sub.code("getAlbum", {"id": "al-999999"}) == 70
    assert sub.code("getAlbum", {}) == 10
    with db.write() as conn:
        conn.execute(update(tracks).where(tracks.c.title == "Something").values(missing_since=now_ms()))
    assert sub.code("getSong", {"id": f"tr-{lib['t']['Something']}"}) == 70  # gone files are invisible
    songs = sub.get("getAlbum", {"id": f"al-{lib['al']['Abbey Road']}"})["album"]["song"]
    assert [s["title"] for s in songs] == ["Come Together"]


def test_folder_view(lib):
    sub = lib["sub"]
    resp = sub.get("getIndexes")["indexes"]
    assert resp["lastModified"] > 0
    beatles = next(a for i in resp["index"] for a in i["artist"] if a["name"] == "The Beatles")
    unchanged = sub.get("getIndexes", {"ifModifiedSince": resp["lastModified"]})["indexes"]
    assert unchanged.get("index", []) == []
    artist_dir = sub.get("getMusicDirectory", {"id": beatles["id"]})["directory"]
    assert artist_dir["name"] == "The Beatles"
    assert [c["title"] for c in artist_dir["child"]] == ["Help!", "Abbey Road"]
    assert all(c["isDir"] for c in artist_dir["child"])
    album_dir = sub.get("getMusicDirectory", {"id": artist_dir["child"][1]["id"]})["directory"]
    assert [c["title"] for c in album_dir["child"]] == ["Come Together", "Something"]
    assert album_dir["parent"] == beatles["id"]


def test_genres(lib):
    genres = {g["value"]: g for g in lib["sub"].get("getGenres")["genres"]["genre"]}
    assert genres["Rock"]["songCount"] == 2 and genres["Rock"]["albumCount"] == 1
    assert genres["Pop"]["songCount"] == 2 and genres["Pop"]["albumCount"] == 2
    songs = lib["sub"].get("getSongsByGenre", {"genre": "pop"})["songsByGenre"]["song"]
    assert {s["title"] for s in songs} == {"Help!", "Dancing Queen"}
    assert lib["sub"].get("getSongsByGenre", {"genre": "Polka"})["songsByGenre"] == {"song": []}


def test_album_lists(lib):
    sub = lib["sub"]

    def names(kind, **extra):
        resp = sub.get("getAlbumList2", {"type": kind, "size": 50, **extra})["albumList2"]
        return [a["name"] for a in resp["album"]]

    assert names("alphabeticalByName") == ["Abbey Road", "Arrival", "Help!", "Hits", "Hot Rats"]
    assert names("alphabeticalByArtist")[0] == "Arrival"  # ABBA
    assert names("byYear", fromYear=1965, toYear=1970) == ["Help!", "Abbey Road", "Hot Rats"]
    assert names("byYear", fromYear=1970, toYear=1965) == ["Abbey Road", "Hot Rats", "Help!"]
    assert names("byGenre", genre="Rock") == ["Abbey Road"]
    assert sorted(names("random")) == sorted(names("alphabeticalByName"))
    assert len(names("newest")) == 5
    assert names("alphabeticalByName", offset=4) == ["Hot Rats"]
    assert len(sub.get("getAlbumList2", {"type": "newest", "size": 2})["albumList2"]["album"]) == 2
    assert names("starred") == [] and names("frequent") == [] and names("highest") == []
    assert sub.code("getAlbumList2", {"type": "nonsense"}) == 0
    assert sub.code("getAlbumList2", {"type": "byGenre"}) == 10
    # played and starred
    sub.get("scrobble", [("id", f"tr-{lib['t']['Help!']}"), ("id", f"tr-{lib['t']['Help!']}")])
    sub.get("scrobble", {"id": f"tr-{lib['t']['Dancing Queen']}"})
    sub.get("star", {"albumId": f"al-{lib['al']['Arrival']}"})
    assert names("frequent") == ["Help!", "Arrival"]
    assert names("recent")[0] in ("Help!", "Arrival")
    assert names("starred") == ["Arrival"]
    old = sub.get("getAlbumList", {"type": "starred"})["albumList"]["album"]
    assert old[0]["isDir"] is True and old[0]["title"] == "Arrival"


def test_random_songs(lib):
    sub = lib["sub"]
    songs = sub.get("getRandomSongs", {"size": 3})["randomSongs"]["song"]
    assert len(songs) == 3 and len({s["id"] for s in songs}) == 3
    assert len(sub.get("getRandomSongs", {"size": 500})["randomSongs"]["song"]) == 6
    pop = sub.get("getRandomSongs", {"size": 10, "genre": "Pop"})["randomSongs"]["song"]
    assert {s["title"] for s in pop} == {"Help!", "Dancing Queen"}
    old = sub.get("getRandomSongs", {"size": 10, "toYear": 1966})["randomSongs"]["song"]
    assert [s["title"] for s in old] == ["Help!"]


def test_random_songs_sampling_in_a_large_library(settings, db, alice):
    from audium.devtools.gen_testlib import generate_db

    generate_db(settings, 600, seed=5)
    songs = alice.get("getRandomSongs", {"size": 100})["randomSongs"]["song"]
    assert len(songs) == 100 and len({s["id"] for s in songs}) == 100


def test_search3(lib):
    sub = lib["sub"]
    resp = sub.get("search3", {"query": "beat"})["searchResult3"]
    assert [a["name"] for a in resp["artist"]] == ["The Beatles"]
    assert {s["title"] for s in sub.get("search3", {"query": "abbey"})["searchResult3"]["song"]} == {
        "Come Together",
        "Something",
    }
    resp = sub.get("search3", {"query": "queen", "artistCount": 0, "albumCount": 0})["searchResult3"]
    assert resp["artist"] == [] and resp["album"] == [] and [s["title"] for s in resp["song"]] == ["Dancing Queen"]
    assert sub.get("search3", {"query": "x"})["searchResult3"]["song"] == []  # too short
    old = sub.get("search2", {"query": "abbey"})["searchResult2"]
    assert old["album"][0]["isDir"] is True


def test_search3_empty_query_syncs_the_whole_library(settings, db, alice):
    from audium.devtools.gen_testlib import generate_db

    generate_db(settings, 700, seed=11)
    seen: list[str] = []
    offset = 0
    while True:
        page = alice.get(
            "search3", {"query": '""', "songCount": 250, "songOffset": offset, "artistCount": 0, "albumCount": 0}
        )["searchResult3"]["song"]
        seen += [s["id"] for s in page]
        offset += 250
        if len(page) < 250:
            break
    assert len(seen) == 700 and len(set(seen)) == 700
    albums_all = alice.get("search3", {"query": "", "albumCount": 1000, "songCount": 0})["searchResult3"]["album"]
    assert len(albums_all) == len({a["id"] for a in albums_all}) > 0


# --- covers ----------------------------------------------------------------------------------


def test_cover_art(lib):
    sub = lib["sub"]
    album = sub.get("getAlbum", {"id": f"al-{lib['al']['Abbey Road']}"})["album"]
    r = sub.raw("getCoverArt", {"id": album["coverArt"], "size": 200}, headers={"Accept": "image/webp,*/*"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert "immutable" in r.headers["cache-control"]
    r = sub.raw("getCoverArt", {"id": album["coverArt"]})  # no WebP in Accept: JPEG
    assert r.headers["content-type"] == "image/jpeg" and r.content[:3] == b"\xff\xd8\xff"
    for item in (album["id"], album["song"][0]["id"], f"ar-{lib['ar']['The Beatles']}"):
        r = sub.raw("getCoverArt", {"id": item, "size": 64})
        assert r.headers["content-type"] == "image/jpeg", item
    from io import BytesIO

    from PIL import Image

    assert Image.open(BytesIO(sub.raw("getCoverArt", {"id": album["coverArt"], "size": 64}).content)).size == (64, 64)
    assert error_code(sub.raw("getCoverArt", {"id": f"al-{lib['al']['Help!']}"})) == 70  # album without cover
    assert error_code(sub.raw("getCoverArt", {"id": "co-" + "0" * 32})) == 70


# --- streaming ------------------------------------------------------------------------------


def test_stream_raw_with_range(lib, library):
    sub = lib["sub"]
    tid = f"tr-{lib['t']['Come Together']}"
    size = (library.root / "Beatles/Abbey Road/01.flac").stat().st_size
    full = sub.raw("stream", {"id": tid})
    assert full.status_code == 200 and full.headers["content-type"] == "audio/flac" and len(full.content) == size
    part = sub.raw("stream", {"id": tid}, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == full.content[10:20]
    assert sub.raw("stream", {"id": tid, "format": "raw", "maxBitRate": 64}).content == full.content
    mp3 = f"tr-{lib['t']['Help!']}"
    r = sub.raw("stream", {"id": mp3, "format": "mp3", "maxBitRate": 320})
    assert r.headers["content-type"] == "audio/mpeg" and "accept-ranges" in r.headers  # already MP3: as is


def test_stream_transcodes(lib):
    sub = lib["sub"]
    flac = f"tr-{lib['t']['Come Together']}"
    kbps = sub.get("getSong", {"id": flac})["song"]["bitRate"]  # a test tone: tiny even as FLAC
    r = sub.raw("stream", {"id": flac, "maxBitRate": kbps})
    assert r.headers["content-type"] == "audio/flac"  # within the limit: the original
    r = sub.raw("stream", {"id": flac, "maxBitRate": max(1, kbps - 1)})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and len(r.content) > 1000
    r = sub.raw("stream", {"id": flac, "format": "opus"})
    assert r.headers["content-type"] == "audio/ogg" and r.content[:4] == b"OggS"
    r = sub.raw("stream", {"id": f"tr-{lib['t']['Peaches En Regalia']}"})  # WMA: always transcoded
    assert r.headers["content-type"] == "audio/mpeg"
    r = sub.raw("stream", {"id": flac, "format": "mp3", "maxBitRate": 64, "estimateContentLength": "true"})
    length = int(r.headers["content-length"])
    assert length == len(r.content) and abs(length - 64 * 1000 // 8) < 1000  # ~1 s at 64 kbit/s
    r = sub.raw("stream", {"id": flac, "format": "mp3", "timeOffset": "0.5"})
    assert error_code(r) == 0  # whole seconds only
    r = sub.raw("stream", {"id": flac, "timeOffset": 1})  # an offset always means transcoding
    assert r.headers["content-type"] == "audio/mpeg" and float(r.headers["x-content-duration"]) < 0.1
    assert error_code(sub.raw("stream", {"id": "tr-999999"})) == 70


def test_download(lib, library):
    sub = lib["sub"]
    r = sub.raw("download", {"id": f"tr-{lib['t']['Peaches En Regalia']}"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.content == (library.root / "Zappa/Hot Rats/01.wma").read_bytes()
    assert error_code(sub.raw("download", {"id": f"al-{lib['al']['Hot Rats']}"})) == 0


# --- favorites, history, now playing ------------------------------------------------------


def test_star_is_the_web_favorite(lib, alice_web):
    sub = lib["sub"]
    song, album, artist = f"tr-{lib['t']['Something']}", f"al-{lib['al']['Arrival']}", f"ar-{lib['ar']['ABBA']}"
    sub.get("star", [("id", song), ("albumId", album), ("artistId", artist)])
    assert [t["title"] for t in alice_web.get("/api/v1/favorites/track").json()["items"]] == ["Something"]
    assert alice_web.get("/api/v1/favorites/album/ids").json()["ids"] == [lib["al"]["Arrival"]]
    starred = sub.get("getStarred2")["starred2"]
    assert [s["title"] for s in starred["song"]] == ["Something"] and starred["song"][0]["starred"].endswith("Z")
    assert [a["name"] for a in starred["album"]] == ["Arrival"]
    assert [a["name"] for a in starred["artist"]] == ["ABBA"]
    assert sub.get("getSong", {"id": song})["song"]["starred"]
    alice_web.delete(f"/api/v1/favorites/track/{lib['t']['Something']}")  # and the other way round
    assert sub.get("getStarred2")["starred2"]["song"] == []
    sub.get("unstar", {"albumId": album})
    assert sub.get("getStarred")["starred"]["album"] == []
    assert sub.code("star", {"id": "tr-999999"}) == 70


def test_scrobble_goes_into_the_history(lib, alice_web):
    sub = lib["sub"]
    tid = lib["t"]["Dancing Queen"]
    past = now_ms() - 3_600_000
    sub.get("scrobble", [("id", f"tr-{tid}"), ("time", past)])
    sub.get("scrobble", {"id": f"tr-{tid}", "submission": "true"})
    history = alice_web.get("/api/v1/history").json()
    assert [h["track"]["id"] for h in history] == [tid, tid]
    assert history[0]["client"] == "pytest" and history[1]["played_at"] == past
    song = sub.get("getSong", {"id": f"tr-{tid}"})["song"]
    assert song["playCount"] == 2 and song["played"]
    alice_web.post("/api/v1/history", json={"track_id": tid, "played_ms": 1000})
    assert alice_web.get("/api/v1/history").json()[0]["client"] is None  # web UI plays


def test_now_playing_is_private(lib, app, alice_web, db):
    sub = lib["sub"]
    sub.get("scrobble", {"id": f"tr-{lib['t']['Something']}", "submission": "false"})
    entries = sub.get("getNowPlaying")["nowPlaying"]["entry"]
    assert [e["title"] for e in entries] == ["Something"]
    assert entries[0]["username"] == "alice" and entries[0]["playerName"] == "pytest" and entries[0]["minutesAgo"] == 0
    assert alice_web.get("/api/v1/history").json() == []  # not a finished play
    create_user(db, "bob", USER_PW)
    bob_web = TestClient(app, headers={"X-Requested-With": "t"})
    login(bob_web, "bob", USER_PW)
    bob = Sub(TestClient(app), "bob", new_app_password(bob_web)["password"])
    assert bob.get("getNowPlaying")["nowPlaying"] == {"entry": []}


def test_top_and_similar_songs(lib):
    sub = lib["sub"]
    sub.get("scrobble", [("id", f"tr-{lib['t']['Something']}")] * 3)
    top = sub.get("getTopSongs", {"artist": "the beatles", "count": 2})["topSongs"]["song"]
    assert [s["title"] for s in top][0] == "Something" and len(top) == 2
    assert sub.get("getTopSongs", {"artist": "Nobody"})["topSongs"] == {"song": []}
    similar = sub.get("getSimilarSongs2", {"id": f"ar-{lib['ar']['The Beatles']}", "count": 10})["similarSongs2"]
    assert similar["song"]  # genre/year fallback without audio analysis
    by_song = sub.get("getSimilarSongs", {"id": f"tr-{lib['t']['Help!']}", "count": 10})["similarSongs"]["song"]
    assert f"tr-{lib['t']['Help!']}" not in [s["id"] for s in by_song]
    info = sub.get("getArtistInfo2", {"id": f"ar-{lib['ar']['The Beatles']}"})["artistInfo2"]
    assert info["biography"] == "" and "The Beatles" not in [a["name"] for a in info.get("similarArtist", [])]
    assert sub.get("getAlbumInfo2", {"id": f"al-{lib['al']['Abbey Road']}"})["albumInfo"]["notes"] == ""


# --- playlists ------------------------------------------------------------------------------


@pytest.fixture
def world(lib, db, app, alice_web):
    """alice owns a playlist; bob edits it, carol views it; dave and the admin have no share."""
    people = {"alice": lib["sub"]}
    for name, role in [("bob", "user"), ("carol", "user"), ("dave", "user"), ("root", "admin")]:
        create_user(db, name, USER_PW, role)
        web = TestClient(app, headers={"X-Requested-With": "t"})
        login(web, name, USER_PW)
        people[name] = Sub(TestClient(app), name, new_app_password(web)["password"])
    t = lib["t"]
    pl = alice_web.post(
        "/api/v1/playlists", json={"name": "Road Trip", "track_ids": [t["Come Together"], t["Something"], t["Help!"]]}
    ).json()
    alice_web.put(f"/api/v1/playlists/{pl['id']}/shares/{entry_owner(db, 'bob')}", json={"role": "editor"})
    alice_web.put(f"/api/v1/playlists/{pl['id']}/shares/{entry_owner(db, 'carol')}", json={"role": "viewer"})
    return {**lib, "pl": pl["id"], "people": people, "web": alice_web}


def _titles(world, who="alice"):
    pl = world["people"][who].get("getPlaylist", {"id": f"pl-{world['pl']}"})["playlist"]
    return [e["title"] for e in pl["entry"]]


SUB_ACTIONS = {
    "view": lambda s, w: s.raw("getPlaylist", {"id": f"pl-{w['pl']}"}),
    "add": lambda s, w: s.raw(
        "updatePlaylist", {"playlistId": f"pl-{w['pl']}", "songIdToAdd": f"tr-{w['t']['Dancing Queen']}"}
    ),
    "remove": lambda s, w: s.raw("updatePlaylist", {"playlistId": f"pl-{w['pl']}", "songIndexToRemove": 0}),
    "replace": lambda s, w: s.raw("createPlaylist", {"playlistId": f"pl-{w['pl']}", "songId": f"tr-{w['t']['1999']}"}),
    "rename": lambda s, w: s.raw("updatePlaylist", {"playlistId": f"pl-{w['pl']}", "name": "Hijacked"}),
    "public": lambda s, w: s.raw("updatePlaylist", {"playlistId": f"pl-{w['pl']}", "public": "true"}),
    "delete": lambda s, w: s.raw("deletePlaylist", {"id": f"pl-{w['pl']}"}),
}
SUB_WHO = {"owner": "alice", "editor": "bob", "viewer": "carol", "stranger": "dave", "admin": "root"}
SUB_ALLOWED = {
    "owner": set(SUB_ACTIONS),
    "editor": {"view", "add", "remove", "replace"},
    "viewer": {"view"},
    "stranger": set(),
    "admin": set(),  # admins manage accounts, not other people's playlists
}


@pytest.mark.parametrize("who", list(SUB_WHO))
@pytest.mark.parametrize("action", list(SUB_ACTIONS))
def test_permission_matrix(world, who, action):
    """The web API's rights (tests/test_playlists.py), repeated against /rest."""
    resp = body(SUB_ACTIONS[action](world["people"][SUB_WHO[who]], world))
    if action in SUB_ALLOWED[who]:
        assert resp["status"] == "ok", (who, action, resp)
    elif who in ("stranger", "admin"):
        assert resp["error"]["code"] == 70, (who, action, resp)  # does not reveal that it exists
    else:
        assert resp["error"]["code"] == 50, (who, action, resp)


def test_denied_writes_change_nothing(world):
    before = _titles(world)
    for who in ("carol", "dave", "root"):
        for action in ("add", "remove", "replace", "rename", "delete"):
            SUB_ACTIONS[action](world["people"][who], world)
    assert _titles(world) == before
    assert world["web"].get(f"/api/v1/playlists/{world['pl']}").json()["name"] == "Road Trip"


def test_playlist_lists_and_details(world):
    lists = {p["name"]: p for p in world["people"]["carol"].get("getPlaylists")["playlists"]["playlist"]}
    road = lists["Road Trip"]
    assert road["id"] == f"pl-{world['pl']}" and road["owner"] == "alice" and road["songCount"] == 3
    assert road["readonly"] is True  # carol only views
    assert world["people"]["bob"].get("getPlaylists")["playlists"]["playlist"][0]["readonly"] is False
    assert world["people"]["dave"].get("getPlaylists")["playlists"] == {"playlist": []}
    detail = world["people"]["alice"].get("getPlaylist", {"id": f"pl-{world['pl']}"})["playlist"]
    assert detail["allowedUser"] == ["bob", "carol"]
    assert [e["title"] for e in detail["entry"]] == ["Come Together", "Something", "Help!"]
    assert world["people"]["alice"].code("getPlaylists", {"username": "bob"}) == 50


def test_playlist_edits(world, db):
    alice = world["people"]["alice"]
    pid = f"pl-{world['pl']}"
    with db.read() as conn:
        seq_before = playlist_service.latest_event_seq(conn)
    alice.get(
        "updatePlaylist",
        [
            ("playlistId", pid),
            ("songIndexToRemove", 0),
            ("songIndexToRemove", 2),
            ("songIdToAdd", f"tr-{world['t']['1999']}"),
        ],
    )
    assert _titles(world) == ["Something", "1999"]
    alice.get("updatePlaylist", {"playlistId": pid, "name": "Road Trip", "comment": "summer", "public": "true"})
    pl = world["web"].get(f"/api/v1/playlists/{world['pl']}").json()
    assert pl["description"] == "summer" and pl["visibility"] == "users" and pl["name"] == "Road Trip"
    # the editor may resend unchanged meta data together with a track change
    world["people"]["bob"].get(
        "updatePlaylist", {"playlistId": pid, "name": "Road Trip", "songIdToAdd": f"tr-{world['t']['Help!']}"}
    )
    assert _titles(world) == ["Something", "1999", "Help!"]
    created = alice.get(
        "createPlaylist",
        [("name", "New"), ("songId", f"tr-{world['t']['Help!']}"), ("songId", f"tr-{world['t']['Help!']}")],
    )["playlist"]
    assert created["name"] == "New" and [e["title"] for e in created["entry"]] == ["Help!", "Help!"]
    replaced = alice.get("createPlaylist", {"playlistId": created["id"], "songId": f"tr-{world['t']['Something']}"})[
        "playlist"
    ]
    assert [e["title"] for e in replaced["entry"]] == ["Something"]
    alice.get("deletePlaylist", {"id": created["id"]})
    assert alice.code("getPlaylist", {"id": created["id"]}) == 70
    with db.read() as conn:
        events = conn.execute(select(playlist_events.c.type).where(playlist_events.c.seq > seq_before)).scalars().all()
    assert {"items", "updated", "created", "deleted"} <= set(events)  # live updates reach the web UI


def test_smart_and_auto_playlists_are_read_only(world, db):
    alice = world["people"]["alice"]
    with db.write() as conn:
        conn.execute(update(playlists).where(playlists.c.id == world["pl"]).values(kind="smart"))
        auto_id = conn.execute(
            insert(auto_playlists).values(
                key="genre:rock",
                generator="tag",
                name="Rock",
                status="published",
                access="all",
                track_count=1,
                duration_ms=1000,
                created_at=1,
                updated_at=1,
                generated_at=now_ms(),
            )
        ).inserted_primary_key[0]
        conn.execute(
            insert(auto_playlist_items).values(auto_playlist_id=auto_id, rank=1, track_id=world["t"]["Something"])
        )
    pid = f"pl-{world['pl']}"
    assert alice.code("updatePlaylist", {"playlistId": pid, "songIdToAdd": f"tr-{world['t']['1999']}"}) == 50
    assert alice.code("createPlaylist", {"playlistId": pid, "songId": f"tr-{world['t']['1999']}"}) == 50
    alice.get("updatePlaylist", {"playlistId": pid, "name": "Smart Trip"})  # renaming is fine
    lists = {p["name"]: p for p in alice.get("getPlaylists")["playlists"]["playlist"]}
    assert lists["Smart Trip"]["readonly"] is True
    rock = lists["Rock"]
    assert rock["id"] == f"ap-{auto_id}" and rock["readonly"] is True and rock["owner"] == "audium"
    assert [e["title"] for e in alice.get("getPlaylist", {"id": rock["id"]})["playlist"]["entry"]] == ["Something"]
    assert alice.code("updatePlaylist", {"playlistId": rock["id"], "name": "x"}) == 50
    assert alice.code("deletePlaylist", {"id": rock["id"]}) == 50
    with db.write() as conn:
        conn.execute(update(auto_playlists).values(access="admin_only"))
    assert alice.code("getPlaylist", {"id": rock["id"]}) == 70


def test_private_playlist_cover_is_not_found_for_others(world):
    assert body(world["people"]["dave"].raw("getCoverArt", {"id": f"pl-{world['pl']}"}))["error"]["code"] == 70


# --- play queue, user, scan ---------------------------------------------------------------


def test_play_queue(lib):
    sub = lib["sub"]
    assert sub.get("getPlayQueue") == {k: v for k, v in sub.get("ping").items()}  # nothing saved
    ids_ = [f"tr-{lib['t']['Help!']}", f"tr-{lib['t']['Something']}"]
    sub.get("savePlayQueue", [("id", ids_[0]), ("id", ids_[1]), ("current", ids_[1]), ("position", 4200)])
    q = sub.get("getPlayQueue")["playQueue"]
    assert [e["id"] for e in q["entry"]] == ids_ and q["current"] == ids_[1] and q["position"] == 4200
    assert q["username"] == "alice" and q["changedBy"] == "pytest" and q["changed"].endswith("Z")
    sub.get("savePlayQueue")
    assert "playQueue" not in sub.get("getPlayQueue")


def test_get_user(world):
    me = world["people"]["bob"].get("getUser", {"username": "bob"})["user"]
    assert me["username"] == "bob" and me["adminRole"] is False and me["streamRole"] is True
    assert isinstance(me["folder"][0], int)
    assert world["people"]["bob"].code("getUser", {"username": "alice"}) == 50
    assert world["people"]["root"].get("getUser", {"username": "alice"})["user"]["username"] == "alice"


def test_scan(world, db):
    status = world["people"]["bob"].get("getScanStatus")["scanStatus"]
    assert status == {"scanning": False, "count": 6}
    assert world["people"]["bob"].code("startScan") == 50
    assert world["people"]["root"].get("startScan")["scanStatus"]["scanning"] is True


def test_admin_login_password_cannot_be_used_either(world, admin_client):
    r = admin_client.get("/rest/ping", params={"f": "json", "u": "admin", "p": ADMIN_PW})
    assert error_code(r) == 40


def test_last_used_is_not_written_on_every_request(lib, db):
    sub = lib["sub"]
    sub.get("ping")
    with db.read() as conn:
        first = conn.execute(select(app_passwords.c.last_used_at)).scalar()
    time.sleep(0.01)
    sub.get("ping")
    with db.read() as conn:
        assert conn.execute(select(app_passwords.c.last_used_at)).scalar() == first
