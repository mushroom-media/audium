import os
import threading

import pytest
from sqlalchemy import select, update

from audium.db.schema import albums, artists, covers, library_roots, tracks
from audium.scanner import scan as scan_module
from audium.scanner.covers import SIZES
from audium.scanner.fallback import from_path
from audium.scanner.tags import parse_number, parse_year, read_track
from audium.services import roots as root_service
from audium.util import now_ms
from tests.conftest import cover_bytes, tags


def _tracks(db, include_missing=False):
    with db.read() as conn:
        q = select(tracks).order_by(tracks.c.rel_path)
        if not include_missing:
            q = q.where(tracks.c.missing_since.is_(None))
        return conn.execute(q).all()


def _albums(db):
    with db.read() as conn:
        return conn.execute(
            select(albums, artists.c.name.label("artist"))
            .join(artists, artists.c.id == albums.c.album_artist_id)
            .where(albums.c.track_count > 0)
            .order_by(albums.c.title)
        ).all()


def _bump_mtime(path):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


# --- formats and tags ----------------------------------------------------------------------

ALL_FORMATS = ["mp3", "flac", "ogg", "opus", "m4a", "alac.m4a", "wma", "wav", "aiff"]


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_reads_tags_and_cover_of_every_format(library, fmt):
    ext = fmt.rsplit(".", 1)[-1]
    path = library.add(
        f"x/song.{ext}",
        tags(
            "Señor Título",
            artist="Björk",
            album="Homogenic",
            track=3,
            disc=2,
            date="1997-09-22",
            albumartist="Björk",
            genre="Electronic",
        ),
        fmt=fmt,
        picture=cover_bytes(),
    )
    meta = read_track(str(path))
    assert meta.error is None
    assert meta.title == "Señor Título"
    assert meta.artists == ["Björk"]
    assert meta.album == "Homogenic"
    assert meta.album_artists == ["Björk"]
    assert meta.track_no == 3
    assert meta.disc_no == 2
    assert meta.year == 1997
    assert meta.genres == ["Electronic"]
    assert meta.picture and meta.picture[:2] == b"\xff\xd8"  # the JPEG we embedded
    assert meta.duration_ms > 500
    expected_codec = {
        "mp3": "mp3",
        "flac": "flac",
        "ogg": "vorbis",
        "opus": "opus",
        "m4a": "aac",
        "alac.m4a": "alac",
        "wma": "wma",
        "wav": "pcm",
        "aiff": "pcm",
    }[fmt]
    assert meta.codec == expected_codec


def test_corrupt_and_empty_files_do_not_raise(tmp_path):
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(os.urandom(5000))
    empty = tmp_path / "empty.flac"
    empty.write_bytes(b"")
    for p in (broken, empty):
        meta = read_track(str(p))
        assert meta.has_tags is False


def test_number_and_year_parsing():
    assert parse_number("3/12") == 3
    assert parse_number("07") == 7
    assert parse_number("A1") is None
    assert parse_number("0") is None
    assert parse_year("1997-09-22") == 1997
    assert parse_year("ca. 1965") == 1965
    assert parse_year("0000") is None


@pytest.mark.parametrize(
    ("rel", "title", "track", "disc", "album", "year", "artist"),
    [
        ("Artist/Album (1999)/03 - Song.mp3", "Song", 3, None, "Album", 1999, "Artist"),
        ("Artist/2001 - Album/1-04 Song.flac", "Song", 4, 1, "Album", 2001, "Artist"),
        ("Artist/Album/CD2/05. Song.mp3", "Song", 5, 2, "Album", None, "Artist"),
        ("Album/1979.mp3", "1979", None, None, "Album", None, None),
        ("loose_track.mp3", "loose track", None, None, None, None, None),
    ],
)
def test_path_fallback(rel, title, track, disc, album, year, artist):
    info = from_path(rel)
    assert (info.title, info.track_no, info.disc_no, info.album, info.album_year, info.artist) == (
        title,
        track,
        disc,
        album,
        year,
        artist,
    )


# --- full scans ----------------------------------------------------------------------------


def test_scan_builds_library(library, db, settings):
    pic = cover_bytes((10, 200, 10))
    for i in range(1, 4):
        library.add(
            f"Band/Record/{i:02d}.mp3",
            tags(f"Song {i}", artist="Band", album="Record", track=i, albumartist="Band", date="2004"),
            picture=pic,
        )
    library.add("Solo/Debut/01.flac", tags("Intro", artist="Solo", album="Debut"))
    (library.root / "Solo/Debut/cover.jpg").write_bytes(cover_bytes((0, 0, 255)))
    library.add("Some Artist/Some Album (1999)/03 - Untagged Song.mp3", None)
    (library.root / "Some Artist/Some Album (1999)/99 - broken.mp3").write_bytes(os.urandom(3000))
    (library.root / "Band/Record/notes.txt").write_text("not music")

    stats = library.scan()
    assert stats.added == 6
    assert stats.errors == 1

    rows = {r.rel_path: r for r in _tracks(db)}
    untagged = rows["Some Artist/Some Album (1999)/03 - Untagged Song.mp3"]
    assert (untagged.title, untagged.track_no, untagged.year, untagged.tag_status) == (
        "Untagged Song",
        3,
        1999,
        "fallback",
    )
    assert untagged.artist_name == "Some Artist"
    assert rows["Some Artist/Some Album (1999)/99 - broken.mp3"].tag_status == "error"

    album_rows = {a.title: a for a in _albums(db)}
    assert album_rows["Record"].track_count == 3
    assert album_rows["Record"].year == 2004
    assert album_rows["Some Album"].artist == "Some Artist"
    with db.read() as conn:
        cover_rows = conn.execute(select(covers)).all()
    # three tracks share one embedded image + one folder image = 2 distinct covers
    assert len(cover_rows) == 2
    for c in cover_rows:
        for size in SIZES:
            assert library.covers.path(c.hash, size).is_file()
    assert {c.source for c in cover_rows} == {"embedded", "folder"}
    with db.read() as conn:
        root = conn.execute(select(library_roots)).one()
    assert root.status == "online"
    assert root.track_count == 6


def test_compilation_and_untagged_album_artist(library, db):
    # No album artist, different track artists in one folder -> one album by "Various Artists"
    library.add("Mix/01.mp3", tags("A", artist="One", album="Summer Mix"))
    library.add("Mix/02.mp3", tags("B", artist="Two", album="Summer Mix"))
    # No album artist, all tracks by the same artist -> that artist
    library.add("Duo/01.mp3", tags("C", artist="Duo", album="Only Duo"))
    library.add("Duo/02.mp3", tags("D", artist="Duo", album="Only Duo"))
    # Compilation flag without album artist
    library.add("Comp/01.m4a", tags("E", artist="Three", album="Hits", compilation="1"))
    library.scan()
    by_title = {a.title: a for a in _albums(db)}
    assert by_title["Summer Mix"].artist == "Various Artists"
    assert by_title["Summer Mix"].track_count == 2
    assert by_title["Only Duo"].artist == "Duo"
    assert by_title["Hits"].artist == "Various Artists"
    assert by_title["Hits"].compilation


def test_multi_disc_folders_form_one_album(library, db):
    library.add("Opera/CD1/01.mp3", tags("Act 1", artist="Composer", album="Opera"))
    library.add("Opera/CD2/01.mp3", tags("Act 2", artist="Composer", album="Opera"))
    (library.root / "Opera/folder.jpg").write_bytes(cover_bytes())
    library.scan()
    rows = _albums(db)
    assert len(rows) == 1
    assert rows[0].track_count == 2
    assert rows[0].cover_id is not None  # parent folder image is used for disc folders
    discs = sorted(t.disc_no for t in _tracks(db))
    assert discs == [1, 2]


def test_same_album_title_by_album_artist_merges_across_folders(library, db):
    library.add("a/01.mp3", tags("X", artist="P", album="Greatest", albumartist="P"))
    library.add("b/02.mp3", tags("Y", artist="P", album="Greatest", albumartist="P"))
    library.scan()
    assert len(_albums(db)) == 1


# --- incremental behaviour -----------------------------------------------------------------


def test_rescan_without_changes_reads_nothing(library, db, monkeypatch):
    for i in range(5):
        library.add(f"A/{i}.mp3", tags(f"T{i}"))
    library.scan()
    library.settings.scan_workers = 1  # read in-process so the patch below sees every read
    calls = []
    monkeypatch.setattr(scan_module, "read_file", lambda *a: calls.append(a) or pytest.fail("re-read"))
    stats = library.scan()
    assert stats.unchanged == 5
    assert (stats.added, stats.updated, stats.missing) == (0, 0, 0)
    assert calls == []


def test_force_rescan_rereads(library, db):
    library.add("A/1.mp3", tags("T"))
    library.scan()
    assert library.scan(force=True).updated == 1


def test_changed_file_is_updated_in_place(library, db):
    path = library.add("A/1.mp3", tags("Old Title"))
    library.scan()
    old_id = _tracks(db)[0].id
    library.add("A/1.mp3", tags("New Title"))
    _bump_mtime(path)
    stats = library.scan()
    assert stats.updated == 1
    row = _tracks(db)[0]
    assert (row.id, row.title) == (old_id, "New Title")


def test_deleted_file_is_soft_deleted_then_restored(library, db):
    library.add("A/1.mp3", tags("Stay"))
    path = library.add("A/2.mp3", tags("Go"))
    library.scan()
    data = path.read_bytes()
    path.unlink()
    stats = library.scan()
    assert stats.missing == 1
    assert [t.title for t in _tracks(db)] == ["Stay"]
    gone = [t for t in _tracks(db, include_missing=True) if t.title == "Go"][0]
    assert gone.missing_since is not None
    assert _albums(db)[0].track_count == 1

    path.write_bytes(data)
    os.utime(path, ns=(gone.mtime_ns, gone.mtime_ns))
    stats = library.scan()
    assert stats.restored == 1
    assert {t.title for t in _tracks(db)} == {"Stay", "Go"}
    assert [t.id for t in _tracks(db) if t.title == "Go"] == [gone.id]


def test_moved_file_keeps_its_id(library, db):
    path = library.add("Old Place/song.flac", tags("Wanderer"))
    library.scan()
    old = _tracks(db)[0]
    target = library.root / "New Place" / "renamed.flac"
    target.parent.mkdir()
    path.rename(target)
    stats = library.scan()
    assert stats.moved == 1
    assert stats.missing == 0
    rows = _tracks(db, include_missing=True)
    assert len(rows) == 1
    assert (rows[0].id, rows[0].rel_path) == (old.id, "New Place/renamed.flac")


def test_copy_is_a_new_track_not_a_move(library, db):
    path = library.add("A/song.mp3", tags("Twin"))
    library.scan()
    (library.root / "B").mkdir()
    (library.root / "B" / "song.mp3").write_bytes(path.read_bytes())
    stats = library.scan()
    assert (stats.added, stats.moved) == (1, 0)
    assert len(_tracks(db)) == 2


def test_empty_or_missing_root_goes_offline_and_keeps_tracks(library, db):
    for i in range(3):
        library.add(f"A/{i}.mp3", tags(f"T{i}"))
    library.scan()
    # Simulate an unmounted share: the mount point exists but is empty.
    import shutil

    shutil.rmtree(library.root / "A")
    stats = library.scan()
    assert stats.missing == 0
    assert len(_tracks(db)) == 3
    with db.read() as conn:
        root = conn.execute(select(library_roots)).one()
    assert root.status == "offline"
    # The folder disappears entirely: still nothing is lost.
    library.root.rmdir()
    library.scan()
    assert len(_tracks(db)) == 3


def test_excluded_folder(library, db, settings):
    library.add("Keep/1.mp3", tags("K"))
    library.add("Skip/1.mp3", tags("S"))
    root_id = library.ensure_root()
    with db.write() as conn:
        root_service.add_exclude(conn, settings, root_id, "Skip")
    library.scan()
    assert [t.title for t in _tracks(db)] == ["K"]


def test_disable_and_reenable_root(library, db):
    library.add("A/1.mp3", tags("T"))
    library.scan()
    root_id = library.ensure_root()
    with db.write() as conn:
        root_service.set_enabled(conn, root_id, False)
    assert _tracks(db) == []
    library.scan()  # disabled roots are not scanned and never purged
    assert _tracks(db) == []
    with db.write() as conn:
        root_service.set_enabled(conn, root_id, True)
    assert library.scan().restored == 1
    assert len(_tracks(db)) == 1


def test_purge_after_grace_period_and_orphan_cleanup(library, db):
    library.add("A/keep.mp3", tags("Keep", artist="Keeper", album="K"))
    path = library.add("B/old.mp3", tags("Old", artist="Leaver", album="L"), picture=cover_bytes((1, 2, 3)))
    library.scan()
    path.unlink()
    library.scan()
    with db.write() as conn:
        conn.execute(update(tracks).where(tracks.c.missing_since.is_not(None)).values(missing_since=1))
    stats = library.scan()
    assert stats.purged == 1
    assert len(_tracks(db, include_missing=True)) == 1
    with db.read() as conn:
        assert [a.name for a in conn.execute(select(artists))] == ["Keeper"]
        assert [a.title for a in conn.execute(select(albums))] == ["K"]
        assert conn.execute(select(covers)).all() == []


def test_cancel_mid_scan_then_resume(library, db, monkeypatch):
    monkeypatch.setattr(scan_module, "BATCH_FILES", 2)
    for d in range(6):
        for i in range(2):
            library.add(f"D{d}/{i}.mp3", tags(f"T{d}{i}", album=f"Album {d}"))

    class StopAfterTwoBatches:
        def __init__(self):
            self.calls = 0
            self.stop = threading.Event()

        def progress(self, *a, **k):
            self.calls += 1
            if self.calls >= 3:
                self.stop.set()

        def should_stop(self):
            return self.stop.is_set()

    stats = library.scan(ctx=StopAfterTwoBatches())
    first = len(_tracks(db))
    assert 0 < first < 12
    assert stats.missing == 0  # an interrupted walk never marks anything missing
    stats = library.scan()
    assert len(_tracks(db)) == 12
    assert stats.added == 12 - first
    assert len({t.rel_path for t in _tracks(db)}) == 12


def test_root_validation(settings, db, tmp_path):
    from audium.errors import BadRequest, Conflict

    (settings.music_dir / "a" / "nested").mkdir(parents=True)
    with db.write() as conn:
        root_service.add_root(conn, settings, str(settings.music_dir / "a"))
        with pytest.raises(BadRequest):
            root_service.add_root(conn, settings, str(tmp_path))  # outside the music mount
        with pytest.raises(BadRequest):
            root_service.add_root(conn, settings, str(settings.music_dir / "a" / ".." / ".." / ".."))
        with pytest.raises(Conflict):
            root_service.add_root(conn, settings, str(settings.music_dir / "a" / "nested"))


def test_initial_root_discovery(settings, db):
    for name in ("a", "b", "@eaDir"):
        (settings.music_dir / name).mkdir()
    with db.write() as conn:
        added = root_service.discover_initial_roots(conn, settings)
        assert sorted(os.path.basename(p) for p in added) == ["a", "b"]
        assert root_service.discover_initial_roots(conn, settings) == []  # only on first start


def test_added_at_uses_file_time_on_first_scan(library, db):
    path = library.add("A/1.mp3", tags("Old file"))
    old_ns = (now_ms() - 400 * 86_400_000) * 1_000_000
    os.utime(path, ns=(old_ns, old_ns))
    library.scan()
    assert _tracks(db)[0].added_at == old_ns // 1_000_000
    library.add("A/2.mp3", tags("New file"))
    p2 = library.root / "A/2.mp3"
    os.utime(p2, ns=(old_ns, old_ns))
    library.scan()
    newest = max(_tracks(db), key=lambda t: t.added_at)
    assert newest.title == "New file"  # later additions use the time audium found them


def test_same_cover_in_parallel_is_processed_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from audium.scanner import covers as covers_module
    from audium.scanner.covers import CoverStore

    store = CoverStore(tmp_path / "covers")
    calls = []
    original = covers_module.render

    def counting(root, data):
        calls.append(data)
        return original(root, data)

    monkeypatch.setattr(covers_module, "render", counting)
    data = cover_bytes((9, 9, 9), 1200)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: store.ingest(data), range(32)))
    assert len(calls) == 1
    assert len(set(results)) == 1 and results[0][1:] == (1200, 1200)
    # after a delete the image is written again
    store.delete(results[0][0])
    assert not store.exists(results[0][0])
    store.ingest(data)
    assert store.exists(results[0][0])
    assert store.ingest(b"not an image") is None


def test_ingest_many_renders_each_distinct_image_once(tmp_path):
    from audium.scanner.covers import CoverStore

    store = CoverStore(tmp_path / "covers")
    red, blue = cover_bytes((255, 0, 0)), cover_bytes((0, 0, 255))
    calls = []

    def mapper(fn, *iterables):
        calls.append(len(iterables[1]))
        return map(fn, *iterables)

    results = store.ingest_many([red, None, red, blue, b"junk", red], mapper)
    assert calls == [3]  # red, blue, junk
    assert results[0] == results[2] == results[5] and results[0] is not None
    assert results[1] is None and results[4] is None
    assert store.ingest_many([blue, red], mapper)[0] == results[3]
    assert calls == [3]  # answered from memory
