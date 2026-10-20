"""Synthetic library for performance tests: `audium gen-testlib`.

files mode: real, tagged audio files (~10 KB each) in Artist/Album (Year)/NN - Title.ext,
            mixed formats, embedded and folder covers, multi-disc albums, compilations,
            untagged and corrupt files. Tests the scanner end to end.
db mode:    the same catalogue written directly into the database through the scanner's
            write path (no files, seconds instead of minutes). Tests API and UI at scale.
"""

import multiprocessing
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from audium.devtools.audiofiles import make_cover, make_templates, write_file

_SYLLABLES = [
    "ka",
    "lo",
    "mi",
    "ra",
    "ne",
    "to",
    "sa",
    "vi",
    "el",
    "an",
    "or",
    "us",
    "be",
    "da",
    "fu",
    "gri",
    "ön",
    "é",
    "ji",
    "qua",
    "zo",
    "lu",
    "ce",
    "mar",
    "tin",
    "vel",
    "sor",
    "dra",
    "ko",
    "nu",
    "pe",
    "ri",
    "sha",
    "ty",
    "wa",
    "ye",
    "bru",
    "cla",
    "dé",
    "fen",
    "glo",
    "hä",
    "ix",
    "jor",
    "kre",
    "lyn",
    "mø",
    "nox",
    "pra",
]
_GENRES = (
    "Rock",
    "Pop",
    "Jazz",
    "Electronic",
    "Hip-Hop",
    "Classical",
    "Metal",
    "Folk",
    "Blues",
    "Soul",
    "Reggae",
    "Punk",
    "Indie",
    "Ambient",
    "Techno",
    "House",
    "Rock; Pop",
    "Electronica",
)
# extension -> share of albums
_FORMAT_WEIGHTS = {
    "mp3": 40,
    "flac": 25,
    "m4a": 10,
    "ogg": 8,
    "opus": 8,
    "alac.m4a": 3,
    "wma": 3,
    "wav": 1,
    "aiff": 2,
}
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(1, 3))).capitalize()


def _name(rng: random.Random, lo: int = 1, hi: int = 3) -> str:
    return " ".join(_word(rng) for _ in range(rng.randint(lo, hi)))


def _safe(s: str) -> str:
    return _UNSAFE.sub("_", s).strip(" .") or "_"


@dataclass
class PlannedTrack:
    title: str
    artist: str
    track: int
    disc: int


@dataclass
class PlannedAlbum:
    index: int
    title: str
    album_artist: str
    year: int
    genre: str
    fmt: str
    cover_mode: str  # embedded | folder | none
    color: tuple[int, int, int]
    multidisc: bool = False
    compilation: bool = False
    untagged: bool = False
    corrupt: bool = False
    tracks: list[PlannedTrack] = field(default_factory=list)


def plan_library(n_tracks: int, seed: int = 42) -> list[PlannedAlbum]:
    rng = random.Random(seed)
    artists: list[str] = []
    albums: list[PlannedAlbum] = []
    total = 0
    formats, weights = zip(*_FORMAT_WEIGHTS.items(), strict=True)
    while total < n_tracks:
        if artists and rng.random() < 0.45:
            artist = rng.choice(artists)
        else:
            artist = ("The " if rng.random() < 0.1 else "") + _name(rng, 1, 2)
            artists.append(artist)
        size = min(rng.randint(6, 16), n_tracks - total)
        roll = rng.random()
        album = PlannedAlbum(
            index=len(albums),
            title=_name(rng, 1, 4),
            album_artist=artist,
            year=rng.randint(1960, 2025),
            genre=rng.choice(_GENRES),
            fmt=rng.choices(formats, weights)[0],
            cover_mode=rng.choices(("embedded", "folder", "none"), (50, 30, 20))[0],
            color=(rng.randrange(256), rng.randrange(256), rng.randrange(256)),
            compilation=roll < 0.03,
            multidisc=0.03 <= roll < 0.06 and size >= 8,
            untagged=0.06 <= roll < 0.07,
            corrupt=rng.random() < 0.003,
        )
        if album.compilation:
            album.album_artist = "Various Artists"
        for i in range(size):
            disc = 1 + (i >= size // 2) if album.multidisc else 1
            number = i + 1 - (size // 2 if album.multidisc and disc == 2 else 0)
            track_artist = _name(rng, 1, 2) if album.compilation else artist
            album.tracks.append(PlannedTrack(_name(rng, 1, 5), track_artist, number, disc))
        albums.append(album)
        total += size
    return albums


def _album_dir(out: Path, a: PlannedAlbum) -> Path:
    return out / _safe(a.album_artist) / _safe(f"{a.title} ({a.year}) [{a.index}]")


def _write_album(args) -> int:
    album, out, templates = args
    out = Path(out)
    base = _album_dir(out, album)
    cover = make_cover(album.color, 1200 if album.index % 7 == 0 else 600) if album.cover_mode != "none" else None
    if album.cover_mode == "folder":
        base.mkdir(parents=True, exist_ok=True)
        (base / "cover.jpg").write_bytes(cover)
    ext = album.fmt.rsplit(".", 1)[-1]
    for t in album.tracks:
        folder = base / f"CD{t.disc}" if album.multidisc else base
        dest = folder / f"{t.track:02d} - {_safe(t.title)}.{ext}"
        tags = (
            None
            if album.untagged
            else {
                "title": t.title,
                "artist": t.artist,
                "albumartist": album.album_artist,
                "album": album.title,
                "track": t.track,
                "disc": t.disc,
                "date": album.year,
                "genre": album.genre,
                "compilation": "1" if album.compilation else None,
            }
        )
        write_file(
            Path(templates[album.fmt]),
            dest,
            album.fmt,
            tags,
            cover if album.cover_mode == "embedded" else None,
        )
    if album.corrupt:
        (base / "99 - broken file.mp3").write_bytes(os.urandom(4096))
    return len(album.tracks)


def generate_files(out: str, n_tracks: int, seed: int = 42) -> None:
    target = Path(out)
    templates = {k: str(v) for k, v in make_templates(target / ".templates").items()}
    albums = plan_library(n_tracks, seed)
    started = time.monotonic()
    done = 0
    with multiprocessing.Pool() as pool:
        jobs = ((a, str(target), templates) for a in albums)
        for i, n in enumerate(pool.imap_unordered(_write_album, jobs, chunksize=8), 1):
            done += n
            if i % 500 == 0:
                print(f"{done}/{n_tracks} tracks, {i}/{len(albums)} albums", flush=True)
    print(f"wrote {done} tracks in {len(albums)} albums to {target} in {time.monotonic() - started:.0f}s")


def generate_db(settings, n_tracks: int, seed: int = 42) -> None:
    from sqlalchemy import select

    from audium.db.engine import Database
    from audium.db.migrate import migrate
    from audium.db.schema import library_roots
    from audium.scanner.covers import CoverStore
    from audium.scanner.scan import Dir, Scanner, Work
    from audium.scanner.tags import TrackMeta
    from audium.util import now_ms

    migrate(settings.db_url, settings.backups_dir)
    db = Database(settings.db_url)
    store = CoverStore(settings.covers_dir)
    scanner = Scanner(db, settings, store)
    synthetic = str(settings.music_dir / "__synthetic__")
    with db.write() as conn:
        root_id = conn.execute(select(library_roots.c.id).where(library_roots.c.path == synthetic)).scalar()
        if root_id is None:
            root_id = conn.execute(
                library_roots.insert().values(path=synthetic, enabled=True, status="online", created_at=now_ms())
            ).inserted_primary_key[0]
    rng = random.Random(seed + 1)
    albums = plan_library(n_tracks, seed)
    started = time.monotonic()
    batch: list = []
    batch_files = done = 0
    ext_codec = {
        "mp3": ("mp3", "mp3"),
        "flac": ("flac", "flac"),
        "m4a": ("aac", "mp4"),
        "ogg": ("vorbis", "ogg"),
        "opus": ("opus", "ogg"),
        "alac.m4a": ("alac", "mp4"),
        "wma": ("wma", "asf"),
        "wav": ("pcm", "wav"),
        "aiff": ("pcm", "aiff"),
    }
    for a in albums:
        cover = store.ingest(make_cover(a.color, 600)) if a.cover_mode != "none" else None
        rel_dir = f"{_safe(a.album_artist)}/{_safe(f'{a.title} ({a.year}) [{a.index}]')}"
        codec, container = ext_codec[a.fmt]
        works = []
        for t in a.tracks:
            meta = TrackMeta(
                title=t.title,
                artist_display=t.artist,
                artists=[t.artist],
                album_artists=[a.album_artist],
                album=a.title,
                track_no=t.track,
                disc_no=t.disc,
                date=str(a.year),
                year=a.year,
                genres=[g.strip() for g in a.genre.split(";")],
                compilation=a.compilation,
                duration_ms=rng.randint(90_000, 480_000),
                bitrate=rng.choice((128_000, 256_000, 320_000, 900_000)),
                sample_rate=44100,
                channels=2,
                codec=codec,
                container=container,
                has_tags=True,
            )
            works.append(
                Work(
                    rel_path=f"{rel_dir}/{t.disc}-{t.track:02d} {_safe(t.title)}.{a.fmt.rsplit('.', 1)[-1]}",
                    size=rng.randint(2_000_000, 40_000_000),
                    mtime_ns=time.time_ns(),
                    existing_id=None,
                    meta=meta,
                    quick_hash=f"{rng.getrandbits(128):032x}",
                    cover=cover,
                )
            )
        batch.append(Dir(rel_dir, works, []))
        batch_files += len(works)
        if batch_files >= 2000:
            scanner.write_batch(root_id, batch, [], False)
            done += batch_files
            batch, batch_files = [], 0
            print(f"{done}/{n_tracks} tracks", flush=True)
    if batch:
        scanner.write_batch(root_id, batch, [], False)
        done += batch_files
    scanner.finalize()
    print(f"inserted {done} tracks in {len(albums)} albums in {time.monotonic() - started:.0f}s")
