import os
import random
import subprocess

import pytest
from sqlalchemy import func, select, update

from audium.analysis import autoplaylists, explain, features, rules
from audium.analysis.genres import normalize
from audium.analysis.tasks import analysis_stats, make_handlers
from audium.db.schema import auto_playlists, genres, track_features, track_genres, tracks
from audium.devtools.gen_testlib import generate_db
from audium.errors import BadRequest
from audium.jobs import queue as jobq
from audium.jobs.worker import Worker
from audium.util import now_ms
from tests.conftest import ADMIN_PW, USER_PW, create_user, login, tags

needs_essentia = pytest.mark.skipif(not features.essentia_available(), reason="Essentia not installed")


# --- genres --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["Rock; Pop"], ["Rock", "Pop"]),
        (["Hip Hop/Rap"], ["Hip-Hop"]),
        (["hiphop", "HIP-HOP"], ["Hip-Hop"]),
        (["Drum & Bass"], ["Drum & Bass"]),
        (["drum and bass", "DnB"], ["Drum & Bass"]),
        (["R&B", "rnb"], ["R&B"]),
        (["Electronica", "EDM"], ["Electronic"]),
        (["deep house"], ["House"]),
        (["post-rock"], ["Post-Rock"]),
        (["shoegaze"], ["Shoegaze"]),
        (["Other", "unknown", "", "  "], []),
        (["Klassik"], ["Classical"]),
        ("Jazz, Blues", ["Jazz", "Blues"]),
        (None, []),
    ],
)
def test_genre_normalization(raw, expected):
    assert normalize(raw) == expected


def test_scanner_writes_normalized_genres(library, db):
    library.add("A/1.mp3", tags("One", genre="Hip Hop; Rap"))
    library.add("A/2.flac", tags("Two", genre="hiphop"))
    library.add("A/3.mp3", tags("Three", genre="Jazz"))
    library.scan()
    with db.read() as conn:
        rows = dict(conn.execute(select(genres.c.name, genres.c.track_count)).all())
    assert rows == {"Hip-Hop": 2, "Jazz": 1}


def test_genre_backfill_job(library, db, settings):
    library.add("A/1.mp3", tags("One", genre="Electronica"))
    library.scan()
    with db.write() as conn:
        conn.execute(track_genres.delete())
        conn.execute(genres.delete())
        jobq.enqueue(conn, "analysis", "genres")
    Worker(db, "analysis", make_handlers(db, settings)).run_one()
    with db.read() as conn:
        assert conn.execute(select(genres.c.name)).scalars().all() == ["Electronic"]


# --- rules ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"conditions": []},
        {"conditions": [{"field": "nope", "op": "=", "value": 1}]},
        {"conditions": [{"field": "bpm", "op": "contains", "value": 1}]},
        {"conditions": [{"field": "energy", "op": ">=", "value": 7}]},
        {"conditions": [{"field": "bpm", "op": "between", "value": [1]}]},
        {"conditions": [{"field": "mode", "op": "is", "value": "lydian"}]},
        {"conditions": [{"field": "artist", "op": "is", "value": "  "}]},
        {"conditions": [{"field": "year", "op": ">", "value": 1990}], "limit": 0},
        {"conditions": [{"field": "year", "op": ">", "value": 1990}], "order": "loudest"},
        {"match": "some", "conditions": [{"field": "year", "op": ">", "value": 1990}]},
    ],
)
def test_rule_validation_rejects(bad):
    with pytest.raises(BadRequest):
        rules.validate(bad)


def test_rule_validation_normalizes():
    r = rules.validate({"conditions": [{"field": "bpm", "op": "between", "value": ["140", 120]}]})
    assert r == {
        "match": "all",
        "conditions": [{"field": "bpm", "op": "between", "value": [120.0, 140.0]}],
        "limit": 200,
        "order": "random",
    }


def test_explain():
    f = {"bpm": 127.6, "energy": 0.8, "danceability": 0.7, "key": "A", "mode": "minor", "brightness": 0.1}
    assert explain.describe(f, ("bpm", "energy", "danceability")) == "128 BPM · hohe Energie · tanzbar"
    assert explain.describe(f, ("key", "brightness")) == "a-Moll · warmer Klang"
    assert explain.describe({"energy": 0.5}, ("energy",)) == ""


# --- analysis ------------------------------------------------------------------------------


def _ffmpeg(out, *args):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args, str(out)], check=True)


@pytest.fixture
def audio_library(library):
    """Real audio with known properties: a 120 BPM click track and a quiet tone."""
    d = library.root / "Real"
    d.mkdir(parents=True)
    _ffmpeg(
        d / "click120.flac",
        "-f",
        "lavfi",
        "-i",
        "aevalsrc='if(lt(mod(t,0.5),0.03),0.8*sin(2*PI*1500*t),0)':s=44100:d=20",
    )
    _ffmpeg(
        d / "quiet.mp3", "-f", "lavfi", "-i", "sine=frequency=220:duration=20:sample_rate=44100", "-af", "volume=0.05"
    )
    (d / "broken.mp3").write_bytes(os.urandom(20000))
    library.scan()
    return library


@needs_essentia
def test_analysis_job_end_to_end(audio_library, db, settings):
    settings.analysis_workers = 1
    worker = Worker(db, "analysis", make_handlers(db, settings))
    with db.write() as conn:
        jobq.enqueue(conn, "analysis", "analyze")
    assert worker.run_one()
    with db.read() as conn:
        rows = {
            r.rel_path.split("/")[-1]: r
            for r in conn.execute(
                select(tracks.c.rel_path, track_features).join(track_features, track_features.c.track_id == tracks.c.id)
            )
        }
        stats = analysis_stats(conn)
    assert rows["click120.flac"].status == "ok"
    assert abs(rows["click120.flac"].bpm - 120) < 1.5
    assert rows["click120.flac"].energy > rows["quiet.mp3"].energy
    assert rows["quiet.mp3"].key == "A"
    assert rows["broken.mp3"].status == "failed" and rows["broken.mp3"].error
    assert stats["pending"] == 0 and stats["analyzed"] == 2 and stats["failed"] == 1
    # Analysing again does nothing: progress lives per track (resumable after restarts).
    while worker.run_one():  # the first run queued an auto-playlist refresh
        pass
    with db.write() as conn:
        jobq.enqueue(conn, "analysis", "analyze")
    while worker.run_one():
        pass
    with db.read() as conn:
        job = conn.execute(
            select(jobq.jobs).where(jobq.jobs.c.type == "analyze").order_by(jobq.jobs.c.id.desc())
        ).first()
    assert job.status == "done" and '"analyzed": 0' in job.result_json
    # A changed file is analysed again.
    path = audio_library.root / "Real" / "quiet.mp3"
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))
    audio_library.scan()
    with db.read() as conn:
        assert analysis_stats(conn)["pending"] == 1


@needs_essentia
def test_analysis_can_be_interrupted_and_resumed(audio_library, db, settings):
    class Stop:
        calls = 0

        def progress(self, *a, **k):
            self.calls += 1

        def should_stop(self):
            return self.calls > 1  # stop after the first batch

        def check(self):
            pass

    from audium.analysis import tasks as analysis_tasks

    monkey_batch = analysis_tasks._BATCH
    analysis_tasks._BATCH = 1
    try:
        analysis_tasks.run_analysis(Stop(), db, settings)
        with db.read() as conn:
            assert analysis_stats(conn)["pending"] == 2

        class Go(Stop):
            def should_stop(self):
                return False

        analysis_tasks.run_analysis(Go(), db, settings)
        with db.read() as conn:
            assert analysis_stats(conn)["pending"] == 0
    finally:
        analysis_tasks._BATCH = monkey_batch


def test_analysis_without_essentia_is_a_clean_no_op(audio_library, db, settings, monkeypatch):
    monkeypatch.setattr(features, "essentia_available", lambda: False)
    from audium.analysis import tasks as analysis_tasks

    result = analysis_tasks.run_analysis(
        type("C", (), {"progress": lambda *a, **k: None, "should_stop": lambda s: False, "check": lambda s: None})(),
        db,
        settings,
    )
    assert "skipped" in result
    with db.read() as conn:
        assert analysis_stats(conn)["backend"] == "none"


# --- auto-playlists ------------------------------------------------------------------------


@pytest.fixture
def analysed(settings, db):
    """1500 synthetic tracks with genres/years and plausible random features."""
    generate_db(settings, 1500, seed=11)
    rng = random.Random(5)
    with db.write() as conn:
        ids = [r[0] for r in conn.execute(select(tracks.c.id))]
        conn.execute(
            track_features.insert(),
            [
                {
                    "track_id": t,
                    "analyzer": "essentia",
                    "analyzer_version": features.ANALYZER_VERSION,
                    "status": "ok",
                    "fingerprint": "x",
                    "bpm": rng.uniform(60, 180),
                    "key": rng.choice(features.KEYS),
                    "mode": rng.choice(["major", "minor"]),
                    "loudness": -10,
                    "energy": rng.random(),
                    "dynamics": rng.random(),
                    "danceability": rng.random(),
                    "brightness": rng.random(),
                    "analyzed_at": now_ms(),
                }
                for t in ids
            ],
        )
    return ids


def test_generation_creates_all_kinds_as_suggestions(analysed, db):
    with db.write() as conn:
        stats = autoplaylists.generate(conn)
        rows = conn.execute(select(auto_playlists)).all()
    kinds = {r.generator for r in rows}
    assert {"tag", "rule", "cluster"} <= kinds
    assert stats["created"] == len(rows)
    assert all(r.status == "suggested" for r in rows)
    names = {r.name for r in rows}
    assert {"Workout", "Zum Entspannen", "Party"} <= names
    assert any(n.startswith("Die ") and n.endswith("er") for n in names)  # decades
    assert any(" der " in n for n in names)  # genre x decade, e.g. "Rock der 90er"
    assert any(n.startswith("Mix: ") for n in names)
    workout = next(r for r in rows if r.key == "rule:workout")
    with db.read() as conn:
        items = conn.execute(
            select(track_features.c.bpm, track_features.c.energy, autoplaylists.auto_playlist_items.c.reason)
            .join(
                autoplaylists.auto_playlist_items,
                autoplaylists.auto_playlist_items.c.track_id == track_features.c.track_id,
            )
            .where(autoplaylists.auto_playlist_items.c.auto_playlist_id == workout.id)
        ).all()
    assert items and all(118 <= i.bpm <= 160 and i.energy >= 0.65 for i in items)
    assert all("BPM" in i.reason for i in items)


def test_regeneration_keeps_admin_decisions(analysed, db):
    with db.write() as conn:
        autoplaylists.generate(conn)
        workout = conn.execute(select(auto_playlists).where(auto_playlists.c.key == "rule:workout")).one()
        party = conn.execute(select(auto_playlists).where(auto_playlists.c.key == "rule:party")).one()
        from audium.services import auto

        auto.admin_update(
            conn,
            workout.id,
            name="Laufen",
            description=None,
            status="published",
            access="restricted",
            user_ids=[],
            rule=None,
        )
        auto.admin_delete(conn, party.id)
        autoplaylists.generate(conn)
        w = conn.execute(select(auto_playlists).where(auto_playlists.c.id == workout.id)).one()
        p = conn.execute(select(auto_playlists).where(auto_playlists.c.id == party.id)).one()
    assert (w.name, w.status, w.access) == ("Laufen", "published", "restricted")
    assert w.track_count > 0
    assert p.status == "dismissed" and p.track_count == 0  # dismissed stays dismissed and empty


@pytest.fixture
def users(db, make_client, admin):
    admin_c = make_client()
    login(admin_c, "admin", ADMIN_PW)
    out = {"admin": (admin, admin_c)}
    for name in ("bob", "carol"):
        u = create_user(db, name, USER_PW)
        c = make_client()
        login(c, name, USER_PW)
        out[name] = (u, c)
    return out


def test_visibility_of_auto_playlists(analysed, db, users):
    admin_c, bob_c, carol_c = users["admin"][1], users["bob"][1], users["carol"][1]
    with db.write() as conn:
        autoplaylists.generate(conn)
    suggestions = admin_c.get("/api/v1/autoplaylists").json()
    assert suggestions and all(a["status"] == "suggested" for a in suggestions)
    assert bob_c.get("/api/v1/autoplaylists").json() == []  # nothing published yet
    workout = next(a for a in suggestions if a["key"] == "rule:workout")
    assert bob_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 404
    assert bob_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"status": "published"}).status_code == 403

    admin_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"status": "published"})
    listed = bob_c.get("/api/v1/autoplaylists").json()
    assert [a["name"] for a in listed] == ["Workout"]
    assert "status" not in listed[0] or listed[0]["status"] is None  # users do not see admin fields
    items = bob_c.get(f"/api/v1/autoplaylists/{workout['id']}/items").json()
    assert items["total"] > 0 and "BPM" in items["items"][0]["reason"]

    bob_id = users["bob"][0].id
    admin_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"access": "restricted", "user_ids": [bob_id]})
    assert bob_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 200
    assert carol_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 404
    admin_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"access": "admin_only"})
    assert bob_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 404
    assert admin_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 200


def test_freeze_copies_into_own_playlist(analysed, db, users):
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    with db.write() as conn:
        autoplaylists.generate(conn)
    workout = next(a for a in admin_c.get("/api/v1/autoplaylists").json() if a["key"] == "rule:workout")
    admin_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"status": "published"})
    r = bob_c.post(f"/api/v1/autoplaylists/{workout['id']}/freeze", json={"name": "Mein Workout"})
    assert r.status_code == 201
    pl = r.json()
    assert pl["kind"] == "frozen_auto" and pl["role"] == "owner" and pl["item_count"] == workout["track_count"]
    # A frozen copy is a normal playlist: editable, shareable
    first = bob_c.get(f"/api/v1/playlists/{pl['id']}/items").json()["items"][0]["item_id"]
    assert bob_c.post(f"/api/v1/playlists/{pl['id']}/items/remove", json={"item_ids": [first]}).status_code == 200


def test_admin_custom_rule_playlist(analysed, db, users):
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    rule = {"conditions": [{"field": "bpm", "op": ">=", "value": 170}], "order": "bpm", "limit": 50}
    r = admin_c.post("/api/v1/admin/autoplaylists", json={"name": "Sehr schnell", "rule": rule})
    assert r.status_code == 201
    auto = r.json()
    assert auto["status"] == "published" and auto["track_count"] > 0
    items = bob_c.get(f"/api/v1/autoplaylists/{auto['id']}/items").json()["items"]
    assert items
    assert bob_c.post("/api/v1/admin/autoplaylists", json={"name": "x", "rule": rule}).status_code == 403
    assert admin_c.delete(f"/api/v1/admin/autoplaylists/{auto['id']}").status_code == 200
    assert admin_c.get(f"/api/v1/autoplaylists/{auto['id']}").status_code == 404


# --- smart playlists -----------------------------------------------------------------------


def test_smart_playlist_lifecycle(analysed, db, users):
    bob_c = users["bob"][1]
    fields = bob_c.get("/api/v1/rules/fields").json()
    assert {"genre", "bpm", "energy", "year"} <= {f["name"] for f in fields["fields"]}
    rule = {
        "match": "all",
        "conditions": [{"field": "year", "op": "between", "value": [1990, 1999]}],
        "limit": 40,
        "order": "year",
    }
    preview = bob_c.post("/api/v1/rules/preview", json={"rule": rule}).json()
    assert preview["count"] == 40 and len(preview["tracks"]) == 20
    assert all(1990 <= t["year"] <= 1999 for t in preview["tracks"])
    pl = bob_c.post("/api/v1/playlists", json={"name": "90er smart", "rule": rule}).json()
    assert pl["kind"] == "smart" and pl["item_count"] == 40 and pl["rule"]["limit"] == 40
    assert bob_c.post(f"/api/v1/playlists/{pl['id']}/items", json={"track_ids": [analysed[0]]}).status_code == 400
    bob_c.patch(f"/api/v1/playlists/{pl['id']}", json={"rule": {**rule, "limit": 10}})
    assert bob_c.get(f"/api/v1/playlists/{pl['id']}").json()["item_count"] == 10
    assert bob_c.post("/api/v1/rules/preview", json={"rule": {"conditions": []}}).status_code == 400
    # Smart playlists follow the library: the generator re-evaluates them.
    with db.write() as conn:
        conn.execute(update(tracks).where(tracks.c.year.between(1990, 1999)).values(year=1985))
        autoplaylists.refresh_smart_playlists(conn)
    assert bob_c.get(f"/api/v1/playlists/{pl['id']}").json()["item_count"] == 0


def test_rule_fields_cover_genre_and_text(analysed, db, users):
    bob_c = users["bob"][1]
    with db.read() as conn:
        top = conn.execute(select(genres.c.name).order_by(genres.c.track_count.desc())).scalar()
    rule = {"conditions": [{"field": "genre", "op": "is", "value": top}], "limit": 1000}
    count = bob_c.post("/api/v1/rules/preview", json={"rule": rule}).json()["count"]
    with db.read() as conn:
        expected = conn.execute(
            select(func.count())
            .select_from(track_genres.join(genres, genres.c.id == track_genres.c.genre_id))
            .where(genres.c.name == top)
        ).scalar_one()
    assert count == min(expected, 1000)
    genre_list = bob_c.get("/api/v1/genres").json()
    assert genre_list[0]["name"] == top


# --- similar & radio -----------------------------------------------------------------------


def test_similar_and_radio(analysed, db, users):
    bob_c = users["bob"][1]
    seed = analysed[10]
    near = bob_c.get(f"/api/v1/tracks/{seed}/similar", params={"limit": 10}).json()
    assert len(near) == 10 and seed not in [t["id"] for t in near]
    with db.read() as conn:
        f = {r.track_id: r for r in conn.execute(select(track_features))}
    me = f[seed]
    d_near = sum(abs(f[t["id"]].energy - me.energy) for t in near) / 10
    d_all = sum(abs(r.energy - me.energy) for r in f.values()) / len(f)
    assert d_near < d_all  # neighbours really are closer than average
    station = bob_c.get(f"/api/v1/tracks/{seed}/radio", params={"limit": 30}).json()
    assert station[0]["id"] == seed and len({t["id"] for t in station}) == len(station) == 30
    albums = [t["album_id"] for t in station]
    assert max(albums.count(a) for a in set(albums)) <= 3  # seed album + at most two more
    assert bob_c.get("/api/v1/tracks/99999999/similar").status_code == 404


def test_similar_falls_back_without_analysis(library, db, users):
    library.add("J/1.mp3", tags("J1", artist="A", genre="Jazz", date="1960"))
    library.add("J/2.mp3", tags("J2", artist="B", genre="Jazz", date="1961"))
    library.add("R/1.mp3", tags("R1", artist="C", genre="Rock", date="1990"))
    library.scan()
    bob_c = users["bob"][1]
    with db.read() as conn:
        j1 = conn.execute(select(tracks.c.id).where(tracks.c.title == "J1")).scalar()
    near = bob_c.get(f"/api/v1/tracks/{j1}/similar").json()
    assert [t["title"] for t in near] == ["J2"]


def test_health_reports_analysis_backend(client, db):
    from audium.db.state import set_state

    with db.write() as conn:
        set_state(conn, "analysis.backend", "essentia")
    assert client.get("/api/health").json()["analysis"] == "essentia"


def test_admin_analysis_endpoints(audio_library, users):
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    status = admin_c.get("/api/v1/admin/analysis").json()
    assert status["tracks"] == 3 and status["pending"] == 3
    assert admin_c.post("/api/v1/admin/analysis/start").status_code == 202
    assert bob_c.get("/api/v1/admin/analysis").status_code == 403
    assert admin_c.get("/api/v1/admin/analysis/failures").json() == []


def test_cluster_mixes_do_not_overlap(analysed, db):
    with db.write() as conn:
        autoplaylists.generate(conn)
        rows = conn.execute(
            select(autoplaylists.auto_playlist_items.c.track_id)
            .join(auto_playlists, auto_playlists.c.id == autoplaylists.auto_playlist_items.c.auto_playlist_id)
            .where(auto_playlists.c.generator == "cluster")
        ).all()
    ids = [r[0] for r in rows]
    assert ids and len(ids) == len(set(ids))
