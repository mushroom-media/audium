from sqlalchemy import select

from audium.db.schema import artists, favorites, play_history, tracks
from audium.services import radio_suggestions as rs
from audium.util import now_ms
from tests.conftest import USER_PW, create_user, tags

DAY = rs.DAY_MS


def _setup(library, db):
    # Lately: Hot (lots), Warm (a few, on album "Warm Up"); before: Old; never played: Fave
    for name, album, n in [
        ("Hot", "Hot Hits", 3),
        ("Warm", "Warm Up", 2),
        ("Old", "Old Days", 2),
        ("Fave", "Faves", 1),
    ]:
        for i in range(n):
            library.add(f"{name}/{i}.mp3", tags(f"{name} {i}", artist=name, album=album, albumartist=name, track=i + 1))
    library.scan()
    with db.read() as conn:
        rows = conn.execute(select(tracks.c.id, artists.c.name).join(artists, artists.c.id == tracks.c.artist_id))
        by_artist: dict[str, list[int]] = {}
        for r in rows:
            by_artist.setdefault(r.name, []).append(r.id)
    return by_artist


def _plays(db, user_id, track_ids, days_ago, times=1):
    now = now_ms()
    with db.write() as conn:
        conn.execute(
            play_history.insert(),
            [
                {"user_id": user_id, "track_id": t, "played_at": now - days_ago * DAY - k, "played_ms": 30_000}
                for t in track_ids
                for k in range(times)
            ],
        )


def test_suggestions_follow_the_listening(library, db, admin, admin_client):
    t = _setup(library, db)
    assert admin_client.get("/api/v1/radio/suggestions").json() == []  # no history, no suggestions

    _plays(db, admin.id, t["Hot"], days_ago=1, times=4)
    _plays(db, admin.id, t["Warm"], days_ago=3, times=2)
    _plays(db, admin.id, t["Old"], days_ago=200, times=4)
    with db.write() as conn:
        conn.execute(
            favorites.insert().values(user_id=admin.id, item_type="track", item_id=t["Fave"][0], created_at=now_ms())
        )

    got = admin_client.get("/api/v1/radio/suggestions").json()
    assert all(s["type"] == "radio" for s in got)
    picks = {(s["radio_of"], s["name"], s["subtitle"]) for s in got}
    assert ("artist", "Hot", "Oft gehört") in picks
    assert ("artist", "Old", "Länger nicht gehört") in picks
    assert ("track", "Fave 0", "Aus deinen Lieblingssongs") in picks
    # each artist only once, whatever the station is built from
    assert len({s["name"] for s in got}) == len(got)
    # stable within a day
    assert admin_client.get("/api/v1/radio/suggestions").json() == got
    assert len(admin_client.get("/api/v1/radio/suggestions", params={"limit": 2}).json()) == 2


def test_suggestions_are_per_user(library, db, admin, admin_client):
    t = _setup(library, db)

    other = create_user(db, "other", USER_PW, "user")
    _plays(db, other.id, t["Hot"], days_ago=1, times=4)
    assert admin_client.get("/api/v1/radio/suggestions").json() == []
