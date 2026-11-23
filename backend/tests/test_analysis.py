import os
import random
import subprocess
import time
from collections import Counter

import numpy as np
import pytest
from sqlalchemy import delete, func, select, update

from audium.analysis import autoplaylists, explain, features, models, rules, similarity, sources, styles, taste
from audium.analysis import tasks as analysis_tasks
from audium.analysis.genres import normalize
from audium.analysis.tasks import analysis_stats, make_handlers
from audium.db.schema import (
    artist_similar,
    artists,
    auto_playlists,
    favorites,
    genres,
    play_history,
    radio_skips,
    track_artists,
    track_embeddings,
    track_features,
    track_genres,
    track_styles,
    tracks,
)
from audium.db.schema import styles as styles_table
from audium.db.state import set_state
from audium.devtools.gen_testlib import generate_db
from audium.errors import BadRequest
from audium.jobs import queue as jobq
from audium.jobs.worker import Worker
from audium.services import auth as auth_service
from audium.services import similar_artists
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
        {"conditions": [{"field": "genre", "op": "is", "value": ["", " "]}]},
        {"conditions": [{"field": "artist", "op": "is", "value": ["a", "b"]}]},
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
    r = rules.validate({"conditions": [{"field": "genre", "op": "is", "value": [" Rock", "Pop", "Rock", ""]}]})
    assert r["conditions"] == [{"field": "genre", "op": "is", "value": ["Rock", "Pop"]}]


def test_explain():
    f = {"bpm": 127.6, "energy": 0.8, "danceability": 0.7, "key": "A", "mode": "minor", "brightness": 0.1}
    assert explain.describe(f, ("bpm", "energy", "danceability")) == "128 BPM · hohe Energie · tanzbar"
    assert explain.describe(f, ("key", "brightness")) == "a-Moll · warmer Klang"
    assert explain.describe({"energy": 0.5}, ("energy",)) == ""
    assert explain.describe(f, ("energy", "key", "brightness"), "en") == "high energy · A minor · warm sound"


def test_tempo_needs_a_steady_beat_and_fixes_double_time():
    assert features._tempo(155.0, 0.2, 1.8) is None  # rubato piano: no beat to count
    assert features._tempo(120.0, 3.7, 4.0) == 120.0
    assert features._tempo(154.0, 2.0, 1.2) == 77.0  # far fewer notes than beats
    assert features._tempo(174.0, 3.5, 6.0) == 174.0  # fast and busy stays fast


def test_energy_is_not_just_loudness():
    calm_but_loud = features._energy(rms_db=-10, onset_rate=1.8, flatness=0.0005, beat_confidence=0.2)
    driving_but_quiet = features._energy(rms_db=-20, onset_rate=4.0, flatness=0.09, beat_confidence=3.7)
    assert calm_but_loud < 0.35 < 0.65 < driving_but_quiet


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

    monkey_batch = analysis_tasks._BATCH_PER_WORKER
    analysis_tasks._BATCH_PER_WORKER = 1
    settings.analysis_workers = 1
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
        analysis_tasks._BATCH_PER_WORKER = monkey_batch


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
    assert {"family", "tag", "rule", "cluster"} <= kinds
    assert stats["created"] == len(rows)
    # Genre and broad-genre playlists are published at once, everything else waits for the admin.
    assert all(r.status == ("published" if r.key.startswith(("genre:", "family:")) else "suggested") for r in rows)
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


def test_worker_generation_writes_in_short_transactions(analysed, db, monkeypatch):
    # The worker computes everything first and then stores in small batches, so other writers
    # (session renewal, play history) never wait behind it for long. A track deleted between
    # both is left out instead of failing the run.
    gone = analysed[0]
    compute = autoplaylists._specs

    def specs_then_delete(conn):
        out = compute(conn)
        with db.write() as w:
            w.execute(delete(tracks).where(tracks.c.id == gone))
        return out

    monkeypatch.setattr(autoplaylists, "_specs", specs_then_delete)
    writes = 0
    write = db.write

    def counting_write(*args, **kwargs):
        nonlocal writes
        writes += 1
        return write(*args, **kwargs)

    monkeypatch.setattr(db, "write", counting_write)
    stats = autoplaylists.generate_in(db)
    with db.read() as conn:
        rows = conn.execute(select(auto_playlists)).all()
        items = set(conn.execute(select(autoplaylists.auto_playlist_items.c.track_id)).scalars())
    assert stats["created"] == len(rows) > autoplaylists.STORE_BATCH
    assert writes >= 1 + len(rows) // autoplaylists.STORE_BATCH  # the delete above, then batches
    assert items and gone not in items
    assert {"family", "tag", "rule", "cluster"} <= {r.generator for r in rows}


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
    genre_kinds = ("genre:", "family:")
    suggestions = [a for a in admin_c.get("/api/v1/autoplaylists").json() if not a["key"].startswith(genre_kinds)]
    assert suggestions and all(a["status"] == "suggested" for a in suggestions)
    # Only the genre playlists are published yet.
    assert all(a["key"].startswith(genre_kinds) for a in bob_c.get("/api/v1/autoplaylists").json())
    workout = next(a for a in suggestions if a["key"] == "rule:workout")
    assert bob_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 404
    assert bob_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"status": "published"}).status_code == 403

    admin_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"status": "published"})
    listed = [a for a in bob_c.get("/api/v1/autoplaylists").json() if not a["key"].startswith(genre_kinds)]
    assert [a["name"] for a in listed] == ["Workout"]
    assert "status" not in listed[0] or listed[0]["status"] is None  # users do not see admin fields
    items = bob_c.get(f"/api/v1/autoplaylists/{workout['id']}/items").json()
    assert items["total"] > 0 and items["items"][0]["reason"] is None  # the "why" is for the admin only
    admin_items = admin_c.get(f"/api/v1/autoplaylists/{workout['id']}/items").json()
    assert "BPM" in admin_items["items"][0]["reason"]

    bob_id = users["bob"][0].id
    admin_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"access": "restricted", "user_ids": [bob_id]})
    assert bob_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 200
    assert carol_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 404
    admin_c.patch(f"/api/v1/admin/autoplaylists/{workout['id']}", json={"access": "admin_only"})
    assert bob_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 404
    assert admin_c.get(f"/api/v1/autoplaylists/{workout['id']}").status_code == 200


def test_auto_playlist_names_in_the_user_language(analysed, db, users):
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    with db.write() as conn:
        autoplaylists.generate(conn)
    bob_c.patch("/api/v1/auth/me/settings", json={"language": "en"})
    german = {a["key"]: a for a in admin_c.get("/api/v1/autoplaylists").json()}
    for a in german.values():
        admin_c.patch(f"/api/v1/admin/autoplaylists/{a['id']}", json={"status": "published"})
    english = {a["key"]: a for a in bob_c.get("/api/v1/autoplaylists").json()}
    assert german["rule:chill"]["name"] == "Zum Entspannen" and english["rule:chill"]["name"] == "To relax"
    assert english["rule:chill"]["description"] == "Calm and slow."
    decades = [k for k in english if k.startswith("decade:")]
    assert decades and all(
        english[k]["name"].startswith("The ") and german[k]["name"].startswith("Die ") for k in decades
    )
    assert any(a["name"].startswith("Mix: ") and a["generator"] == "cluster" for a in english.values())
    # A name the admin gives is the same for everybody.
    chill = german["rule:chill"]["id"]
    admin_c.patch(f"/api/v1/admin/autoplaylists/{chill}", json={"name": "Abends"})
    assert bob_c.get(f"/api/v1/autoplaylists/{chill}").json()["name"] == "Abends"


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


def test_rule_preview_for_filling_a_playlist(analysed, db, users):
    """The "fill automatically" dialog: the whole list, another selection per seed, removed tracks
    replaced by the next ones."""
    bob_c = users["bob"][1]
    rule = {"conditions": [{"field": "year", "op": "between", "value": [1990, 1999]}], "limit": 30}

    def preview(**extra) -> list[int]:
        r = bob_c.post("/api/v1/rules/preview", json={"rule": rule, **extra})
        assert r.status_code == 200
        return [t["id"] for t in r.json()["tracks"]]

    full = preview(tracks=30)
    assert len(full) == 30 and full == preview(tracks=30)
    assert preview(tracks=30, seed=7) != full
    removed = full[:3]
    rest = preview(tracks=30, exclude=removed)
    assert len(rest) == 30 and not set(removed) & set(rest) and rest[:27] == full[3:]
    assert bob_c.post("/api/v1/rules/preview", json={"rule": rule, "tracks": 5000}).status_code == 422


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

    # several genres in one condition: tracks with any of them
    two = [g["name"] for g in genre_list[:2]]
    rule = {"conditions": [{"field": "genre", "op": "is", "value": two}], "limit": 1000}
    count = bob_c.post("/api/v1/rules/preview", json={"rule": rule}).json()["count"]
    with db.read() as conn:
        expected = conn.execute(
            select(func.count(func.distinct(track_genres.c.track_id)))
            .select_from(track_genres.join(genres, genres.c.id == track_genres.c.genre_id))
            .where(genres.c.name.in_(two))
        ).scalar_one()
    assert count == min(expected, 1000)


def _primary(db, artist_id: int) -> set[int]:
    with db.read() as conn:
        return set(conn.execute(select(tracks.c.id).where(tracks.c.artist_id == artist_id)).scalars())


def test_rule_in_the_direction_of_an_artist(analysed, db, users):
    bob_c = users["bob"][1]

    def matching(name: str) -> set[int]:
        rule = {"conditions": [{"field": "like_artist", "op": "is", "value": [name]}], "limit": 1000}
        r = bob_c.post("/api/v1/rules/preview", json={"rule": rule}).json()
        assert r["count"] < 1000
        with db.read() as conn:
            return set(conn.execute(rules.query(rules.validate(rule))).scalars())

    def tracks_of(artist_id: int) -> set[int]:  # also as a guest
        with db.read() as conn:
            guest = select(track_artists.c.track_id).where(track_artists.c.artist_id == artist_id)
            stmt = select(tracks.c.id).where((tracks.c.artist_id == artist_id) | tracks.c.id.in_(guest))
            return set(conn.execute(stmt).scalars())

    with db.read() as conn:
        a, b = conn.execute(select(artists.c.id, artists.c.name).order_by(artists.c.id).limit(2)).all()
        styled = conn.execute(
            select(func.count())
            .select_from(track_styles.join(tracks, tracks.c.id == track_styles.c.track_id))
            .where(tracks.c.artist_id == a.id, track_styles.c.prob >= styles.MIN_STYLE_PROB)
        ).scalar()
    # No similar artists known: the artist's own tracks and tracks in their styles.
    alone = matching(a.name.upper())
    assert tracks_of(a.id) <= alone
    assert (len(alone) > len(tracks_of(a.id))) == bool(styled)
    # Primary-artist tracks of the similar one; guest appearances of it don't count.
    b_own = _primary(db, b.id)
    try:
        with db.write() as conn:
            conn.execute(artist_similar.insert().values(artist_id=a.id, similar_id=b.id, score=1.0))
        # Known similar artists: their tracks instead of the styles.
        assert matching(a.name) == tracks_of(a.id) | b_own
    finally:
        with db.write() as conn:
            conn.execute(delete(artist_similar).where(artist_similar.c.artist_id == a.id))


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


def test_album_and_artist_radio(analysed, db, users):
    bob_c = users["bob"][1]
    with db.read() as conn:
        album_id, artist_id = conn.execute(
            select(tracks.c.album_id, tracks.c.artist_id).where(tracks.c.id == analysed[10])
        ).one()
        album_tracks = set(conn.execute(select(tracks.c.id).where(tracks.c.album_id == album_id)).scalars())
        artist_tracks = set(
            conn.execute(select(track_artists.c.track_id).where(track_artists.c.artist_id == artist_id)).scalars()
        )
    for path, own_tracks in ((f"albums/{album_id}", album_tracks), (f"artists/{artist_id}", artist_tracks)):
        station = [t["id"] for t in bob_c.get(f"/api/v1/{path}/radio", params={"limit": 40}).json()]
        assert len(station) == len(set(station)) == 40
        own = [t for t in station if t in own_tracks]
        assert station[0] in own_tracks
        assert len(own) == min(10, len(own_tracks))  # about a quarter, spread over the station
        assert len(own) == 1 or station.index(own[-1]) > 20
    assert bob_c.get("/api/v1/albums/99999999/radio").status_code == 404
    assert bob_c.get("/api/v1/artists/99999999/radio").status_code == 404


def test_radio_continues_without_repeats(analysed, db, users):
    """A playing station fetches its next tracks with the ones it already had excluded."""
    bob_c = users["bob"][1]
    seed = analysed[10]
    with db.read() as conn:
        album_id = conn.execute(select(tracks.c.album_id).where(tracks.c.id == seed)).scalar()
        album_tracks = set(conn.execute(select(tracks.c.id).where(tracks.c.album_id == album_id)).scalars())
    for path in (f"tracks/{seed}", f"albums/{album_id}"):
        first = [t["id"] for t in bob_c.get(f"/api/v1/{path}/radio", params={"limit": 20}).json()]
        more = [t["id"] for t in bob_c.get(f"/api/v1/{path}/radio", params={"limit": 20, "exclude": first}).json()]
        assert len(more) == 20 and not set(first) & set(more)
        if path.startswith("albums"):
            assert set(more) & album_tracks or album_tracks <= set(first)  # own tracks keep coming
    station = bob_c.get(f"/api/v1/tracks/{seed}/radio", params={"limit": 5, "exclude": [seed]}).json()
    assert seed not in [t["id"] for t in station]  # a continued station does not restart at its seed


def test_vector_index_refreshes_in_background(analysed, db):
    """Only the first load happens in the request; later reloads swap in when they are done."""
    index = similarity.VectorIndex(db)
    seed = analysed[10]
    with db.read() as conn:
        assert index.nearest(conn, seed, 5)
        before = index._features
    with db.write() as conn:
        set_state(conn, similarity.ANALYSIS_GENERATION, "changed")
    with db.read() as conn:
        assert index.nearest(conn, seed, 5)  # answered at once, from the old matrices
    for _ in range(200):
        if index._features is not before:
            break
        time.sleep(0.01)
    assert index._features is not before and index._generation == "changed"


def _wait(condition, seconds=60):
    for _ in range(seconds * 20):
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_vector_index_builds_files_in_its_own_process(analysed, db, settings):
    """The server never builds in a request or in its own process, and comes back from the files."""
    directory = settings.data_dir / "vectors"
    seed = analysed[10]
    index = similarity.VectorIndex(db, directory=directory)
    index.warm()
    with db.read() as conn:
        assert index.nearest(conn, seed, 5) is None or index._features.ids.size  # answers while it builds
    assert _wait(lambda: index._features.ids.size)
    assert (directory / "features.npz").exists()

    again = similarity.VectorIndex(db, directory=directory)
    again.warm()
    assert _wait(lambda: again._features.ids.size)
    assert again._generation == index._generation
    with db.read() as conn:
        assert again.nearest(conn, seed, 5)

    with db.write() as conn:
        set_state(conn, similarity.ANALYSIS_GENERATION, "changed")
    with db.read() as conn:
        assert again.nearest(conn, seed, 5)  # from the old file meanwhile
    assert _wait(lambda: again._generation == "changed")


def test_album_radio_falls_back_without_analysis(library, db, users):
    library.add("J/1.mp3", tags("J1", artist="A", album="Blue", genre="Jazz", date="1960"))
    library.add("J/2.mp3", tags("J2", artist="A", album="Blue", genre="Jazz", date="1960"))
    library.add("K/1.mp3", tags("K1", artist="B", album="Kind", genre="Jazz", date="1959"))
    library.add("S/1.mp3", tags("S1", artist="C", album="Surf", genre="Surf", date="1963"))
    library.add("R/1.mp3", tags("R1", artist="D", album="Loud", genre="Rock", date="1994"))
    library.scan()
    bob_c = users["bob"][1]
    with db.read() as conn:
        album_id = conn.execute(select(tracks.c.album_id).where(tracks.c.title == "J1")).scalar()
    station = [t["title"] for t in bob_c.get(f"/api/v1/albums/{album_id}/radio", params={"limit": 8}).json()]
    assert station[0] in {"J1", "J2"}
    # The same genre qualifies; the same decade alone (Surf, 1963) does not, nor the 90s Rock.
    assert sorted(t for t in station if t not in {"J1", "J2"}) == ["K1"]


def test_health_reports_analysis_backend(client, db):
    from audium.db.state import set_state

    with db.write() as conn:
        set_state(conn, "analysis.backend", "essentia")
    assert client.get("/api/health").json()["analysis"] == "essentia"


def test_admin_analysis_endpoints(audio_library, users):
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    status = admin_c.get("/api/v1/admin/analysis").json()
    assert status["tracks"] == 3 and status["pending"] == 3
    assert status["fingerprints"] == 0 and status["styles"] == 0
    assert status["waiting"] is None and status["cpus"] >= 1 and status["workers_default"] == 1
    assert len(status["server_time"]) == 5
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


# --- styles, detected genres, fingerprints -------------------------------------------------


def test_style_to_genre_table():
    assert styles.genre_of("Electronic---Deep House") == "House"
    assert styles.genre_of("Electronic---Ambient") == "Ambient"
    assert styles.genre_of("Electronic---IDM") == "Electronic"  # not listed: the top genre's default
    assert styles.genre_of("Rock---Shoegaze") == "Indie"
    assert styles.genre_of("Rock---Thrash") == "Metal"
    assert styles.genre_of("Hip Hop---Boom Bap") == "Hip-Hop"
    assert styles.genre_of("Hip Hop---RnB/Swing") == "R&B"
    assert styles.genre_of("Funk / Soul---Neo Soul") == "Soul"
    assert styles.genre_of("Non-Music---Spoken Word") == "Audiobook"
    assert styles.genre_of("Non-Music---Comedy") is None
    assert styles.genre_of("Unknown---Thing") is None
    # Every genre a style can map to is one of the canonical genre names.
    targets = {g for default, exc in styles._TABLE.values() for g in [default, *exc.values()] if g}
    assert targets <= set(normalize_aliases_values())


def normalize_aliases_values() -> set[str]:
    from audium.analysis.genres import ALIASES

    return set(ALIASES.values())


def _add_styles(conn, assignments: dict[int, list[tuple[str, float]]]) -> None:
    cache: dict[str, int] = {}
    ids = styles.style_ids(conn, {label for found in assignments.values() for label, _p in found}, cache)
    conn.execute(
        track_styles.insert(),
        [{"track_id": t, "style_id": ids[label], "prob": p} for t, found in assignments.items() for label, p in found],
    )


def test_detected_genres_fill_untagged_tracks_smoothed_by_album(library, db):
    for i in range(1, 5):
        library.add(f"H/{i}.mp3", tags(f"H{i}", artist="DJ", album="Club", track=i))
    library.add("T/1.mp3", tags("Tagged", artist="Band", album="Live", genre="Rock"))
    library.scan()
    with db.write() as conn:
        tid = dict(conn.execute(select(tracks.c.title, tracks.c.id)).all())
        house = [("Electronic---Deep House", 0.8), ("Electronic---Tech House", 0.4)]
        _add_styles(
            conn,
            {
                tid["H1"]: house,
                tid["H2"]: house,
                tid["H3"]: house,
                tid["H4"]: [("Electronic---Techno", 0.7)],  # the odd one out on a house album
                tid["Tagged"]: [("Electronic---Trance", 0.9)],  # the tag wins
            },
        )
        analysis_tasks.refresh_detected_genres(conn)
        rows = conn.execute(
            select(tracks.c.title, genres.c.name, track_genres.c.source, track_genres.c.weight)
            .join(track_genres, track_genres.c.track_id == tracks.c.id)
            .join(genres, genres.c.id == track_genres.c.genre_id)
        ).all()
        by_track: dict[str, list] = {}
        for r in rows:
            by_track.setdefault(r.title, []).append((r.name, r.source, r.weight))
        counts = dict(conn.execute(select(genres.c.name, genres.c.track_count)).all())
        style_counts = dict(conn.execute(select(styles_table.c.name, styles_table.c.track_count)).all())
    assert by_track["Tagged"] == [("Rock", "tag", 1.0)]
    assert by_track["H1"] == [("House", "detected", 1.0)]
    # Half its own Techno, half the album average (mostly House): both, Techno weighs more.
    h4 = dict((g, w) for g, _s, w in by_track["H4"])
    assert set(h4) == {"House", "Techno"} and h4["Techno"] > h4["House"] and abs(sum(h4.values()) - 1) < 0.01
    assert counts["House"] == 4 and counts["Techno"] == 1 and counts["Rock"] == 1
    assert style_counts["Deep House"] == 3 and style_counts["Tech House"] == 3  # prob >= 0.3
    # A new genre tag replaces the detected genres on the next run.
    library.add("H/4.mp3", tags("H4", artist="DJ", album="Club", track=4, genre="Techno"))
    library.scan()
    with db.write() as conn:
        analysis_tasks.refresh_detected_genres(conn)
        h4_rows = conn.execute(
            select(genres.c.name, track_genres.c.source)
            .join(track_genres, track_genres.c.genre_id == genres.c.id)
            .where(track_genres.c.track_id == tid["H4"])
        ).all()
    assert [tuple(r) for r in h4_rows] == [("Techno", "tag")]


def test_style_playlists_and_rules(analysed, db, users):
    with db.write() as conn:
        _add_styles(conn, {t: [("Rock---Shoegaze", 0.9)] for t in analysed[:40]})
        _add_styles(conn, {t: [("Jazz---Cool Jazz", 0.9)] for t in analysed[40:50]})  # too few
        analysis_tasks.refresh_detected_genres(conn)
        autoplaylists.generate(conn)
        keys = set(conn.execute(select(auto_playlists.c.key)).scalars())
    assert "style:rockshoegaze" in keys and "style:jazzcooljazz" not in keys
    admin_c = users["admin"][1]
    preview = admin_c.post(
        "/api/v1/rules/preview",
        json={"rule": {"conditions": [{"field": "style", "op": "is", "value": "shoegaze"}], "limit": 100}},
    ).json()
    assert preview["count"] == 40 and preview["needs_analysis"]
    listed = admin_c.get("/api/v1/styles").json()
    assert listed[0] == {"name": "Shoegaze", "genre": "Indie", "track_count": 40}
    origins = {a["key"]: (a["origin"], a["detected_tracks"]) for a in admin_c.get("/api/v1/autoplaylists").json()}
    assert origins["style:rockshoegaze"] == ("styles", None)
    assert origins["rule:workout"] == ("features", None)
    genre_origins = [v for k, v in origins.items() if k.startswith("genre:")]
    assert genre_origins and all(o == "tags" and isinstance(n, int) for o, n in genre_origins)


def _embed(conn, vectors: dict[int, np.ndarray]) -> None:
    conn.execute(
        track_embeddings.insert(),
        [
            {"track_id": t, "model": features.EMBEDDING_MODEL, "vector": v.astype(np.float16).tobytes()}
            for t, v in vectors.items()
        ],
    )


def test_similarity_prefers_fingerprints(analysed, db, users):
    rng = np.random.default_rng(3)
    centers = rng.normal(size=(3, 1280))
    embedded = analysed[:600]
    with db.write() as conn:
        _embed(conn, {t: centers[t % 3] + rng.normal(scale=0.3, size=1280) for t in embedded})
    bob_c = users["bob"][1]
    seed = embedded[7]
    near = [t["id"] for t in bob_c.get(f"/api/v1/tracks/{seed}/similar", params={"limit": 20}).json()]
    assert len(near) == 20 and all(t % 3 == seed % 3 for t in near)  # same "sound" only
    # A track without a fingerprint still gets neighbours from the hand-made descriptors.
    plain = analysed[1000]
    assert len(bob_c.get(f"/api/v1/tracks/{plain}/similar", params={"limit": 5}).json()) == 5


def test_sound_only_source(analysed, db, users):
    """With source "sound" only detected styles and mixes over the fingerprints are suggested."""
    rng = np.random.default_rng(4)
    centers = rng.normal(size=(3, 1280))
    labels = ["Rock---Shoegaze", "Electronic---Deep House", "Jazz---Cool Jazz"]
    embedded = analysed[:900]
    with db.write() as conn:
        _embed(conn, {t: centers[i % 3] + rng.normal(scale=0.3, size=1280) for i, t in enumerate(embedded)})
        _add_styles(conn, {t: [(labels[i % 3], 0.8)] for i, t in enumerate(embedded)})
        analysis_tasks.refresh_detected_genres(conn)
        autoplaylists.generate(conn)  # "all" first: genre, decade, rule and cluster suggestions
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    assert admin_c.get("/api/v1/admin/autoplaylists/source").json() == {"source": "all"}
    assert bob_c.put("/api/v1/admin/autoplaylists/source", json={"source": "sound"}).status_code == 403
    assert admin_c.put("/api/v1/admin/autoplaylists/source", json={"source": "x"}).status_code == 422
    assert admin_c.put("/api/v1/admin/autoplaylists/source", json={"source": "sound"}).json() == {"source": "sound"}
    with db.write() as conn:
        assert autoplaylists.source(conn) == "sound"
        autoplaylists.generate(conn)
        rows = conn.execute(select(auto_playlists)).all()
        sound_items = conn.execute(
            select(autoplaylists.auto_playlist_items.c.track_id, autoplaylists.auto_playlist_items.c.reason)
            .join(auto_playlists, auto_playlists.c.id == autoplaylists.auto_playlist_items.c.auto_playlist_id)
            .where(auto_playlists.c.generator == "sound")
        ).all()
    keys = {r.key for r in rows}
    assert {r.generator for r in rows} == {"tag", "sound"}  # the old suggestions are gone
    assert {"style:rockshoegaze", "style:electronicdeephouse", "style:jazzcooljazz"} <= keys
    assert all(k.startswith(("style:", "sound:", "family:")) for k in keys)  # families from detected genres
    for slug in ("rockshoegaze", "electronicdeephouse", "jazzcooljazz"):
        assert any(k.startswith(f"sound:{slug}") for k in keys)
    # Every mix holds one sound only, named after its style, and mixes do not overlap.
    by_key = {r.key: r for r in rows}
    assert by_key["sound:rockshoegaze"].name == "Mix: Shoegaze"
    ids = [r.track_id for r in sound_items]
    assert ids and len(ids) == len(set(ids)) and set(ids) <= set(embedded)
    assert {r.reason for r in sound_items} == {"Shoegaze", "Deep House", "Cool Jazz"}
    origins = {a["key"]: a["origin"] for a in admin_c.get("/api/v1/autoplaylists").json()}
    assert set(origins.values()) == {"styles"}


def test_embedding_matrix_is_reduced_and_normalized(analysed, db):
    rng = np.random.default_rng(1)
    with db.write() as conn:
        _embed(conn, {t: rng.normal(size=1280) for t in analysed[:300]})
        conn.execute(
            track_embeddings.insert().values(track_id=analysed[300], model=features.EMBEDDING_MODEL, vector=None)
        )
    with db.read() as conn:
        ids, z = similarity.embedding_matrix(conn, dims=32)
    assert list(ids) == sorted(analysed[:300]) and z.shape == (300, 32)
    assert np.allclose(np.linalg.norm(z, axis=1), 1, atol=1e-4)


def test_analysis_queues_tracks_without_fingerprint(audio_library, db, settings, monkeypatch):
    with db.write() as conn:
        set_state(conn, analysis_tasks.BACKEND_STATE, "essentia")
        ids = list(conn.execute(select(tracks.c.id)).scalars())
        conn.execute(
            track_features.insert(),
            [
                {"track_id": t, "analyzer": "essentia", "analyzer_version": features.ANALYZER_VERSION,
                 "status": "ok", "fingerprint": fp, "analyzed_at": 1}
                for t, fp in conn.execute(select(tracks.c.id, analysis_tasks._fingerprint_sql()))
            ],
        )  # fmt: skip
        assert analysis_stats(conn)["pending"] == 0
        set_state(conn, analysis_tasks.BACKEND_STATE, "essentia+effnet")
        assert analysis_stats(conn)["pending"] == len(ids)
        _embed(conn, {ids[0]: np.zeros(1280)})
        assert analysis_stats(conn)["pending"] == len(ids) - 1


def test_model_download_checks_the_checksum(tmp_path, monkeypatch):
    import hashlib
    import io

    good, bad = b"model-bytes", b"tampered"
    monkeypatch.setattr(
        models, "FILES", {"a.pb": ("x/a.pb", hashlib.sha256(good).hexdigest()), "b.json": ("x/b.json", "0" * 64)}
    )
    served = {"x/a.pb": good, "x/b.json": bad}
    monkeypatch.setattr(
        models.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(served[url.removeprefix(models.BASE_URL)])
    )
    assert not models.ensure(tmp_path, download=True)
    assert (tmp_path / "a.pb").read_bytes() == good
    assert not (tmp_path / "b.json").exists() and not list(tmp_path.glob("*.part"))
    assert not models.ensure(tmp_path / "other", download=False)


# --- processes, pause, time window -----------------------------------------------------------


def _set(db, **values):
    from audium.services import server_settings

    with db.write() as conn:
        server_settings.update_server_settings(conn, values)


def test_analysis_blocked_by_pause_and_time_window(db, settings):
    from datetime import datetime

    from audium.analysis.tasks import analysis_blocked, analysis_workers

    at = lambda h: datetime(2026, 10, 26, h, 30)  # noqa: E731
    with db.read() as conn:
        assert analysis_blocked(conn, at(14)) is None
        assert analysis_workers(conn, settings) == settings.analysis_workers
    _set(db, analysis_schedule="window")  # default 01-07, across no midnight
    with db.read() as conn:
        assert [h for h in range(24) if analysis_blocked(conn, at(h)) is None] == [1, 2, 3, 4, 5, 6]
    _set(db, analysis_from="22", analysis_until="02", analysis_workers="3")
    with db.read() as conn:
        assert [h for h in range(24) if analysis_blocked(conn, at(h)) is None] == [0, 1, 22, 23]
        assert analysis_blocked(conn, at(12)) == "window"
        assert analysis_workers(conn, settings) == 3
    _set(db, analysis_from="05", analysis_until="05")  # an empty window would never run: means always
    _set(db, analysis_paused="on")
    with db.read() as conn:
        assert analysis_blocked(conn, at(12)) == "paused"
    with pytest.raises(BadRequest):
        _set(db, analysis_workers="99")


@needs_essentia
def test_paused_analysis_waits_and_resumes(audio_library, db, settings, monkeypatch):
    from audium.analysis.tasks import WAITING_STATE, AnalysisScheduler, run_analysis
    from audium.db.state import get_state

    ctx = type("C", (), {"progress": lambda *a, **k: None, "should_stop": lambda s: False, "check": lambda s: None})()
    _set(db, analysis_paused="on")
    result = run_analysis(ctx, db, settings)
    assert result["waiting"] == "paused" and result["analyzed"] == 0
    with db.read() as conn:
        assert get_state(conn, WAITING_STATE) == "paused" and analysis_stats(conn)["pending"] == 3
        assert analysis_stats(conn)["waiting"] == "paused"

    with db.write() as conn:
        auth_service.finish_setup(conn)  # the scheduler waits for the first-run dialog
    scheduler = AnalysisScheduler(db, settings)
    scheduler()  # first tick: the usual start-up work
    with db.write() as conn:
        conn.execute(jobq.jobs.delete())
    monkeypatch.setattr(analysis_tasks, "_RESUME_CHECK_S", 0)
    scheduler()  # still paused: nothing
    with db.read() as conn:
        assert conn.execute(select(func.count()).select_from(jobq.jobs)).scalar_one() == 0
    _set(db, analysis_paused="off")
    scheduler()
    with db.read() as conn:
        assert [j.type for j in conn.execute(select(jobq.jobs.c.type))] == ["analyze"]
        assert get_state(conn, WAITING_STATE) == ""
    assert run_analysis(ctx, db, settings)["analyzed"] == 2


def test_changing_analysis_settings_resumes_at_once(audio_library, users, db):
    admin_c = users["admin"][1]
    r = admin_c.patch("/api/v1/admin/settings", json={"analysis_paused": "on", "analysis_workers": "2"})
    assert r.status_code == 200 and r.json()["analysis_workers"] == "2" and r.json()["analysis_schedule"] == "always"
    assert admin_c.get("/api/v1/admin/analysis").json()["waiting"] == "paused"
    with db.write() as conn:
        conn.execute(jobq.jobs.delete())
    admin_c.patch("/api/v1/admin/settings", json={"analysis_paused": "off"})
    with db.read() as conn:
        assert [j.type for j in conn.execute(select(jobq.jobs.c.type))] == ["analyze"]
    assert admin_c.patch("/api/v1/admin/settings", json={"analysis_from": "25"}).status_code in (400, 422)
    assert users["bob"][1].patch("/api/v1/admin/settings", json={"analysis_paused": "on"}).status_code == 403


# --- Discover: broad genres, rediscover ---------------------------------------------------------


@pytest.mark.parametrize(
    ("genre", "family"),
    [
        ("Rock", "Rock"),
        ("Alternative", "Rock"),
        ("Punk", "Rock"),
        ("Post-Punk", "Rock"),
        ("Metal", "Metal"),
        ("Folk Metal", "Metal"),
        ("Folk Rock", "Rock"),
        ("Deutschrap", "Hip-Hop"),
        ("Trip Hop", "Electronic"),
        ("Dancehall", "Reggae"),
        ("Dubstep", "Electronic"),
        ("Neo-Soul", "R&B & Soul"),
        ("Classical", "Klassik"),
        ("Symphonic", "Klassik"),
        ("K-Pop", "Pop"),
        ("Audiobook", None),
        ("Lo-Fi", None),
    ],
)
def test_genre_families(genre, family):
    from audium.analysis.genres import family as family_of

    assert family_of(genre) == family


def test_family_playlists_cover_their_genres(analysed, db):
    with db.write() as conn:
        autoplaylists.generate(conn)
        rows = {r.key: r for r in conn.execute(select(auto_playlists)).all()}
    rock = rows["family:rock"]
    assert rock.generator == "family" and rock.status == "published" and rock.name == "Rock"
    with db.read() as conn:
        reasons = set(
            conn.execute(
                select(autoplaylists.auto_playlist_items.c.reason).where(
                    autoplaylists.auto_playlist_items.c.auto_playlist_id == rock.id
                )
            ).scalars()
        )
        rock_genres = {n for n in conn.execute(select(genres.c.name)).scalars() if normalize_family(n) == "Rock"}
    assert reasons and reasons <= rock_genres  # every track is there by one of the family's genres
    assert "family:metal" in rows  # Metal is a family of its own
    assert all(not k.startswith("family:") or rows[k].track_count >= autoplaylists.MIN_GENRE_TRACKS for k in rows)

    # Hidden by the admin: stays hidden, also when generated again.
    from audium.services import auto

    with db.write() as conn:
        auto.admin_delete(conn, rock.id)
        autoplaylists.generate(conn)
        assert (
            conn.execute(select(auto_playlists.c.status).where(auto_playlists.c.id == rock.id)).scalar() == "dismissed"
        )


def normalize_family(name):
    from audium.analysis.genres import family

    return family(name)


def test_discover_genres_puts_your_genres_first(analysed, db, users):
    bob_c, bob = users["bob"][1], users["bob"][0]
    with db.write() as conn:
        autoplaylists.generate(conn)
        jazz_track = conn.execute(
            select(tracks.c.id)
            .join(track_genres, track_genres.c.track_id == tracks.c.id)
            .join(genres, genres.c.id == track_genres.c.genre_id)
            .where(genres.c.name == "Jazz")
            .limit(1)
        ).scalar_one()
    for _ in range(3):
        bob_c.post("/api/v1/history", json={"track_id": jazz_track, "played_ms": 60_000})
    overview = bob_c.get("/api/v1/discover/genres").json()
    families = overview["families"]
    assert families[0]["name"] == "Jazz" and families[0]["plays"] == 3
    rest = [f["playlist"]["track_count"] for f in families[1:]]
    assert rest == sorted(rest, reverse=True)  # unplayed ones by size
    rock = next(f for f in families if f["name"] == "Rock")
    assert any(g["name"] == "Rock" for g in rock["genres"])
    assert all(g["key"].startswith("genre:") for f in families for g in f["genres"])
    # Another user without plays: by size only.
    carol = users["carol"][1].get("/api/v1/discover/genres").json()["families"]
    assert [f["playlist"]["track_count"] for f in carol] == sorted(
        (f["playlist"]["track_count"] for f in carol), reverse=True
    )
    assert bob.id


@pytest.mark.parametrize(
    ("genre", "family", "parent"),
    [
        ("Rock", "Rock", None),
        ("Hard Rock", "Rock", "Rock"),
        ("Indie", "Rock", "Rock"),
        ("Shoegaze", "Rock", "Indie"),  # style table: a rock style counted for Indie
        ("Krautrock", "Rock", "Rock"),  # compound word
        ("Garage Rock", "Rock", "Rock"),
        ("Folk Rock", "Rock", "Rock"),  # the style table says Folk, but the family is Rock
        ("Neofolk", "Folk & Country", "Folk"),
        ("Hardbop", "Jazz", "Jazz"),
        ("Synthpop", "Pop", "Pop"),
        ("Deutschrap", "Hip-Hop", "Hip-Hop"),
        ("Soul", "R&B & Soul", None),
        ("Lo-Fi", None, None),  # rock style or lo-fi hip-hop: no guess
        ("Audiobook", None, None),
    ],
)
def test_genre_parents(genre, family, parent):
    from audium.analysis import genres as genre_norm

    assert genre_norm.family(genre) == family
    assert genre_norm.parent(genre) == parent


def test_genre_playlists_need_variety(analysed, db, users):
    """A genre of one artist counts for its parent genre; a varied one keeps its playlist; no
    artist fills a genre playlist."""
    with db.write() as conn:
        rows = conn.execute(select(tracks.c.id, tracks.c.artist_id).order_by(tracks.c.id)).all()
        artist_ids = sorted({r.artist_id for r in rows})
        kraut, shoe = [r.id for r in rows[:35]], [r.id for r in rows[100:160]]
        conn.execute(update(tracks).where(tracks.c.id.in_(kraut)).values(artist_id=artist_ids[0]))
        for i, t in enumerate(shoe):
            conn.execute(update(tracks).where(tracks.c.id == t).values(artist_id=artist_ids[1 + i % 6]))
        for name, ids in (("Krautrock", kraut), ("Shoegaze", shoe)):
            gid = conn.execute(genres.insert().values(name=name, slug=name.lower(), track_count=len(ids)))
            gid = gid.inserted_primary_key[0]
            conn.execute(track_genres.insert(), [{"track_id": t, "genre_id": gid} for t in ids])
        autoplaylists.generate(conn)
        lists = {r.key: r for r in conn.execute(select(auto_playlists))}

        def reasons(key):
            return [
                (t, reason)
                for t, reason in conn.execute(
                    select(
                        autoplaylists.auto_playlist_items.c.track_id, autoplaylists.auto_playlist_items.c.reason
                    ).where(autoplaylists.auto_playlist_items.c.auto_playlist_id == lists[key].id)
                )
            ]

        assert "genre:krautrock" not in lists
        assert "genre:shoegaze" in lists and "Shoegaze" in lists["genre:shoegaze"].description
        rock = reasons("genre:rock")
        assert any(r == "Krautrock" for _, r in rock)  # one artist's Krautrock counts for Rock
        assert "Krautrock" in lists["genre:rock"].description
        artist_of = dict(conn.execute(select(tracks.c.id, tracks.c.artist_id)).all())
        for key in lists:
            if key.startswith(("genre:", "family:")):
                items = reasons(key)
                per_artist = Counter(artist_of[t] for t, _ in items)
                assert max(per_artist.values()) <= autoplaylists._artist_cap(10_000), key

    # The admin lets every genre have its own playlist.
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    rules_ = {"min_artists": 1, "max_artist_share": 1.0}
    assert bob_c.put("/api/v1/admin/autoplaylists/genre-rules", json=rules_).status_code == 403
    bad = {"min_artists": 4, "max_artist_share": 1.0}
    assert admin_c.put("/api/v1/admin/autoplaylists/genre-rules", json=bad).status_code == 400
    assert admin_c.put("/api/v1/admin/autoplaylists/genre-rules", json=rules_).json() == rules_
    assert admin_c.get("/api/v1/admin/autoplaylists/genre-rules").json() == rules_
    with db.write() as conn:
        autoplaylists.generate(conn)
        keys = set(conn.execute(select(auto_playlists.c.key)).scalars())
    assert "genre:krautrock" in keys


def test_rediscover_finds_what_you_stopped_playing(analysed, db, users):
    from audium.services import discover

    bob = users["bob"][0]
    now = now_ms()
    day = 86_400_000
    with db.write() as conn:
        rows = conn.execute(select(tracks.c.id, tracks.c.album_id, tracks.c.artist_id).order_by(tracks.c.id)).all()
        by_album = {}
        for r in rows:
            by_album.setdefault(r.album_id, []).append(r)
        old_album, busy_album, few_album = list(by_album)[:3]

        def play(album_id, days_ago, times):
            track = by_album[album_id][0]
            conn.execute(
                play_history.insert(),
                [
                    {"user_id": bob.id, "track_id": track.id, "played_at": now - days_ago * day, "played_ms": 1}
                    for _ in range(times)
                ],
            )

        play(old_album, 120, 6)  # used to play a lot, not since: rediscover
        play(busy_album, 120, 6)
        play(busy_album, 3, 1)  # played again lately: not
        play(few_album, 200, 2)  # never played much: not
        found = discover.rediscover(conn, bob, limit=8, now=now)
    album_ids = {f["id"] for f in found if f["type"] == "album"}
    artist_ids = {f["id"] for f in found if f["type"] == "artist"}
    old_artist = by_album[old_album][0].artist_id
    assert busy_album not in album_ids and few_album not in album_ids
    assert (old_album in album_ids) != (old_artist in artist_ids)  # album or its artist, not both
    assert all(f["last_played"] < now - 60 * day and f["cover"] for f in found)
    assert users["bob"][1].get("/api/v1/discover/rediscover").status_code == 200
    assert users["carol"][1].get("/api/v1/discover/rediscover").json() == []


# --- radio sources (analysis/sources.py) and similar artists --------------------------------


def test_radio_sources_settings(db, users):
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    got = admin_c.get("/api/v1/admin/radio/sources").json()["sources"]
    assert got["sound"] == {"on": True, "weight": 100} and got["artists"]["on"] is False  # ListenBrainz off
    assert bob_c.get("/api/v1/admin/radio/sources").status_code == 403
    r = admin_c.patch("/api/v1/admin/radio/sources", json={"genre": {"weight": 60}, "features": {"on": False}})
    assert r.json()["sources"]["genre"] == {"on": True, "weight": 60} and not r.json()["sources"]["features"]["on"]
    assert admin_c.patch("/api/v1/admin/radio/sources", json={"genre": {"weight": 0}}).status_code == 422
    assert admin_c.patch("/api/v1/admin/radio/sources", json={"sound": {"on": False}}).status_code == 200
    assert admin_c.patch("/api/v1/admin/radio/sources", json={"taste": {"on": False}}).status_code == 200
    # The last switched-on source stays on.
    assert admin_c.patch("/api/v1/admin/radio/sources", json={"genre": {"on": False}}).status_code == 400
    assert admin_c.get("/api/v1/admin/radio/sources").json()["sources"]["genre"]["on"] is True


def test_station_reasons_for_admins_only(analysed, db, users):
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    seed = analysed[10]
    assert all(t["reason"] is None for t in bob_c.get(f"/api/v1/tracks/{seed}/radio", params={"limit": 10}).json())
    station = admin_c.get(f"/api/v1/tracks/{seed}/radio", params={"limit": 10}).json()
    assert station[0]["reason"] == "Startpunkt" and all(t["reason"] for t in station)
    with db.read() as conn:
        album_id = conn.execute(select(tracks.c.album_id).where(tracks.c.id == seed)).scalar()
    album = admin_c.get(f"/api/v1/albums/{album_id}/radio", params={"limit": 10}).json()
    assert album[0]["reason"] == "Vom Album"
    # Only genre & year on: that is what every reason says.
    admin_c.patch("/api/v1/admin/radio/sources", json={"sound": {"on": False}, "features": {"on": False}})
    near = admin_c.get(f"/api/v1/tracks/{seed}/similar", params={"limit": 10}).json()
    assert near and all(t["reason"].startswith("Genre") for t in near)


def test_switched_off_sources_drop_their_mixes(analysed, db):
    with db.write() as conn:
        autoplaylists.generate(conn)
        assert conn.execute(select(func.count()).where(auto_playlists.c.generator == "cluster")).scalar() > 0
        sources.save(conn, {"features": {"on": False}})
        autoplaylists.generate(conn)
        assert conn.execute(select(func.count()).where(auto_playlists.c.generator == "cluster")).scalar() == 0


def test_similar_artists_from_listenbrainz(library, db, users):
    for artist, genre in (("Alpha", "Jazz"), ("Beta", "Rock"), ("Gamma", "Pop"), ("Nobody", "Folk")):
        for i in range(3):
            library.add(f"{artist}/{i}.mp3", tags(f"{artist} {i}", artist=artist, genre=genre, date="2000"))
    library.scan()
    mbids = {"Alpha": "a" * 8 + "-1111-1111-1111-" + "1" * 12, "Beta": "b" * 8 + "-2222-2222-2222-" + "2" * 12}
    with db.write() as conn:
        for name, mbid in mbids.items():
            conn.execute(update(artists).where(artists.c.name == name).values(mb_artist_id=mbid))
        sources.save(conn, {"artists": {"on": True}})

    asked: list[str] = []

    def fetch(mbid):
        asked.append(mbid)
        if mbid == mbids["Alpha"]:  # Beta by id, Gamma by name, one not in the library at all
            return [(mbids["Beta"], "Beta", 200.0), ("c" * 36, "gamma", 100.0), ("d" * 36, "Elsewhere", 50.0)]
        return []

    stats = similar_artists.run_batch(db, fetch=fetch, lookup=lambda name: None, pause=lambda s: None)
    assert stats["artists"] == 4 and stats["no_mbid"] == 2 and stats["left"] == 0
    assert sorted(asked) == sorted(mbids.values())  # artists without an id are only looked up
    with db.read() as conn:
        ids = dict(conn.execute(select(artists.c.name, artists.c.id)).tuples().all())
        got = similar_artists.similar_to(conn, [ids["Alpha"]])
    assert [(a, round(s, 2)) for a, s, _ in got] == [(ids["Beta"], 1.0), (ids["Gamma"], 0.5)]

    # "Ask again" makes every artist due, and keeps the old answers until the new ones are in.
    admin_c, bob_c = users["admin"][1], users["bob"][1]
    assert bob_c.post("/api/v1/admin/similar-artists/refresh").status_code == 403
    assert admin_c.post("/api/v1/admin/similar-artists/refresh").status_code == 202
    with db.read() as conn:
        assert similar_artists.count_pending(conn) == 4
        assert len(similar_artists.similar_to(conn, [ids["Alpha"]])) == 2

    # Only this source on: Alpha's radio is Alpha plus their fans' artists, and says so.
    admin_c.patch("/api/v1/admin/radio/sources", json={"sound": {"on": False}, "features": {"on": False}})
    admin_c.patch("/api/v1/admin/radio/sources", json={"genre": {"on": False}})
    station = admin_c.get(f"/api/v1/artists/{ids['Alpha']}/radio", params={"limit": 9}).json()
    others = [t for t in station if t["artist"] != "Alpha"]
    assert others and {t["artist"] for t in others} <= {"Beta", "Gamma"}
    assert all(t["reason"] == f"Fans von Alpha hören auch {t['artist']}" for t in others)
    # Nobody has no similar artists: genre & year stand in rather than an empty station.
    station = admin_c.get(f"/api/v1/artists/{ids['Nobody']}/radio", params={"limit": 6}).json()
    assert all(t["reason"] == "Vom Künstler" or t["reason"].startswith("Ersatz") for t in station)

    admin_c.patch("/api/v1/admin/radio/sources", json={"artists": {"on": False}, "genre": {"on": True}})
    assert admin_c.post("/api/v1/admin/similar-artists/refresh").status_code == 409


def test_mbid_of_tag_values():
    one = "5b11f4ce-a62d-471e-81fc-a69a8278c7da"
    assert similar_artists.mbid_of(f"{one.upper()}; 8bfac288-ccc5-448d-9573-c33ea2aa5c30") == one
    assert similar_artists.mbid_of("not an id") is None and similar_artists.mbid_of(None) is None


def _rank(found: similarity.Blend, track_id: int) -> int:
    return [t for t, _ in found.picks].index(track_id)


def test_taste_moves_liked_tracks_up(analysed, db, users):
    bob, carol = users["bob"][0], users["carol"][0]
    index = similarity.VectorIndex(db)
    seed = analysed[10]
    with db.read() as conn:
        plain = similarity.blend(conn, index, [seed], 100)
    liked = plain.picks[80][0]
    with db.write() as conn:
        conn.execute(favorites.insert().values(user_id=bob.id, item_type="track", item_id=liked, created_at=now_ms()))
        conn.execute(
            play_history.insert(),
            [{"user_id": bob.id, "track_id": liked, "played_at": now_ms(), "played_ms": 1000}] * 4,
        )
    with db.read() as conn:
        mine = similarity.blend(conn, index, [seed], 100, bob.id)
        theirs = similarity.blend(conn, index, [seed], 100, carol.id)
        assert _rank(mine, liked) < 80 and "taste" in dict(mine.picks)[liked]
        assert _rank(theirs, liked) == 80  # nobody else's taste
        # Taste only reorders: it brings in nothing the other sources did not find.
        assert {t for t, _ in mine.picks} <= {t for t, _ in similarity.blend(conn, index, [seed], 300).picks}
    with db.write() as conn:
        sources.save(conn, {"taste": {"on": False}})
    with db.read() as conn:
        assert _rank(similarity.blend(conn, index, [seed], 100, bob.id), liked) == 80


def test_radio_skips_count_in_similar_stations_only(analysed, db, users):
    (bob, bob_c), carol = users["bob"], users["carol"][0]
    index = similarity.VectorIndex(db)
    seed = analysed[10]
    with db.write() as conn:
        sources.save(conn, {"taste": {"on": False}})
    with db.read() as conn:
        top = similarity.blend(conn, index, [seed], 50).picks[0][0]
        seed_artist = conn.execute(select(tracks.c.artist_id).where(tracks.c.id == seed)).scalar()
        same_artist = conn.execute(
            select(tracks.c.id).where(tracks.c.artist_id == seed_artist, tracks.c.id != seed)
        ).scalar()
        other = conn.execute(select(tracks.c.id).where(tracks.c.artist_id != seed_artist)).scalar()
    assert bob_c.post("/api/v1/radio/skips", json={"track_id": top, "station": f"track:{seed}"}).json() == {"ok": True}
    # Not counted: the station's own seed, or no station at all.
    bob_c.post("/api/v1/radio/skips", json={"track_id": seed, "station": f"track:{seed}"})
    bob_c.post("/api/v1/radio/skips", json={"track_id": top, "station": "playlist:3"})
    with db.read() as conn:
        assert conn.execute(select(func.count()).select_from(radio_skips)).scalar() == 1
        same = similarity.blend(conn, index, [seed], 300, bob.id, f"track:{seed}")
        assert _rank(same, top) > 0 and same.skipped[top] == pytest.approx(1 / 3, abs=0.01)
        # The same artist's station: less; an unrelated one, someone else, or no radio: not at all.
        assert taste.skip_penalties(conn, bob.id, f"track:{same_artist}", [top])[top] == pytest.approx(
            1 / 2.2, abs=0.01
        )
        assert taste.skip_penalties(conn, bob.id, f"artist:{seed_artist}", [top])[top] < 1
        assert taste.skip_penalties(conn, bob.id, f"track:{other}", [top]) == {}
        assert taste.skip_penalties(conn, carol.id, f"track:{seed}", [top]) == {}
        assert similarity.blend(conn, index, [seed], 50, bob.id).picks[0][0] == top  # "similar tracks"
        # ListenBrainz says the other artist is like the seed's: a skip counts a little there.
        other_artist = conn.execute(select(tracks.c.artist_id).where(tracks.c.id == other)).scalar()
    with db.write() as conn:
        conn.execute(artist_similar.insert().values(artist_id=seed_artist, similar_id=other_artist, score=1.0))
    with db.read() as conn:
        assert taste.skip_penalties(conn, bob.id, f"track:{other}", [top])[top] == pytest.approx(1 / 1.8, abs=0.01)
    # Old skips fade and are forgotten.
    with db.write() as conn:
        conn.execute(update(radio_skips).values(skipped_at=now_ms() - 200 * 86_400_000))
        taste.prune_skips(conn)
        assert conn.execute(select(func.count()).select_from(radio_skips)).scalar() == 0


def test_radio_dislikes_stay_out_of_that_station(analysed, db, users):
    (bob, bob_c), carol = users["bob"], users["carol"][0]
    index = similarity.VectorIndex(db)
    seed, other_seed = analysed[10], analysed[40]
    with db.write() as conn:
        sources.save(conn, {"taste": {"on": False}})
    with db.read() as conn:
        top = similarity.blend(conn, index, [seed], 300, bob.id, f"track:{seed}").picks[0][0]
        album = conn.execute(select(tracks.c.album_id).where(tracks.c.id == seed)).scalar()
        own = list(conn.execute(select(tracks.c.id).where(tracks.c.album_id == album)).scalars())
    body = {"track_id": top, "station": f"track:{seed}"}
    assert bob_c.post("/api/v1/radio/dislikes", json=body).json() == {"ok": True}
    # The seed can't be disliked: a track's station always starts with it.
    bob_c.post("/api/v1/radio/dislikes", json={"track_id": seed, "station": f"track:{seed}"})
    with db.read() as conn:
        assert taste.dislikes(conn, bob.id, f"track:{seed}") == {top}
        assert top not in dict(similarity.blend(conn, index, [seed], 300, bob.id, f"track:{seed}").picks)
        # Only that station, only that user.
        assert taste.dislikes(conn, bob.id, f"track:{other_seed}") == set()
        assert top in dict(similarity.blend(conn, index, [seed], 300, carol.id, f"track:{seed}").picks)
    # A group station leaves out its own tracks too, even when none of them is left.
    for t in own:
        bob_c.post("/api/v1/radio/dislikes", json={"track_id": t, "station": f"album:{album}"})
    rng = np.random.default_rng(1)
    with db.read() as conn:
        station = similarity.group_radio(conn, index, own, 20, rng, (), bob.id, f"album:{album}")
        assert station.picks and not {t for t, _ in station.picks} & set(own)


def test_track_info(analysed, db, users):
    bob_c = users["bob"][1]
    seed = analysed[10]
    info = bob_c.get(f"/api/v1/tracks/{seed}/info").json()
    assert info["track"]["id"] == seed and info["analysis"]["status"] == "ok" and info["analysis"]["bpm"] > 0
    assert info["genres"] and info["plays"] == 0 and info["last_played"] is None and info["favorite"] is False
    bob_c.post("/api/v1/history", json={"track_id": seed, "played_ms": 60_000})
    assert bob_c.get(f"/api/v1/tracks/{seed}/info").json()["plays"] == 1
    assert bob_c.get("/api/v1/tracks/999999/info").status_code == 404


def test_radio_avoids_tempo_jumps(analysed, db, users):
    admin_c = users["admin"][1]
    seed = analysed[10]
    with db.read() as conn:
        bpm = dict(conn.execute(select(track_features.c.track_id, track_features.c.bpm)).all())
        picks = [(t, {}) for t in analysed[10:60]]
        smooth = similarity.smooth_tempo(conn, picks)
    steps = lambda ids: sum(similarity._tempo_step(bpm[a], bpm[b]) for a, b in zip(ids, ids[1:], strict=False))  # noqa: E731
    assert smooth[0][0] == seed and sorted(t for t, _ in smooth) == sorted(t for t, _ in picks)
    assert steps([t for t, _ in smooth]) < steps([t for t, _ in picks]) * 0.7
    assert similarity._tempo_step(70, 140) == 0 and similarity._tempo_step(100, 125) > 0.3
    # A switch on the radio settings page.
    assert admin_c.get("/api/v1/admin/radio/sources").json()["options"] == {"smooth_tempo": True}
    r = admin_c.patch("/api/v1/admin/radio/options", json={"smooth_tempo": False})
    assert r.json()["options"]["smooth_tempo"] is False
    with db.read() as conn:
        assert sources.options(conn)["smooth_tempo"] is False
