"""Incremental library scanner.

Per library root:
1. Walk the tree. A file whose (size, mtime) matches the DB costs one stat() and nothing else:
   no tag read, no DB write.
2. New/changed files are read in a thread pool (I/O bound on NAS shares), then written in
   batches of BATCH_FILES per transaction, so the API keeps serving reads during a scan.
3. A new file with the quick hash and size of a known track whose file is gone is treated as
   a move: the track keeps its id, and with it playlists, favorites and history.
4. Only after a complete walk are unseen tracks marked missing (soft delete). A root that is
   gone or empty is marked offline and nothing is marked missing, because an unmounted share
   must not look like deleted music.
5. Missing tracks are purged after AUDIUM_MISSING_GRACE_DAYS.

Interrupting a scan at any point is safe: committed batches stay, the next run skips them
because their (size, mtime) now match.
"""

import multiprocessing
import os
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

import xxhash
from sqlalchemy import Connection, bindparam, select, text, update

from audium.analysis import genres as genre_norm
from audium.config import Settings
from audium.db import search
from audium.db.engine import Database
from audium.db.schema import (
    albums,
    artists,
    covers,
    genres,
    library_excludes,
    library_roots,
    track_artists,
    track_genres,
    tracks,
)
from audium.db.state import bump_library_generation
from audium.logging import get_logger
from audium.scanner.covers import CoverStore
from audium.scanner.fallback import (
    UNKNOWN_ALBUM,
    UNKNOWN_ARTIST,
    VARIOUS_ARTISTS,
    album_dir_of,
    from_path,
    is_disc_dir,
)
from audium.scanner.formats import ARTIST_IMAGE_EXTENSIONS, ARTIST_IMAGE_STEM, FOLDER_COVER_NAMES
from audium.scanner.tags import TrackMeta, read_track
from audium.scanner.walk import iter_dirs
from audium.services.server_settings import server_setting
from audium.util import norm, now_ms, sort_key

log = get_logger(__name__)

BATCH_FILES = 300
_RESTORE_BATCH = 2000
_HASH_CHUNK = 64 * 1024
_CHUNK = 500


@dataclass
class ScanStats:
    roots: int = 0
    files_seen: int = 0
    unchanged: int = 0
    added: int = 0
    updated: int = 0
    moved: int = 0
    restored: int = 0
    missing: int = 0
    purged: int = 0
    errors: int = 0
    covers_added: int = 0
    offline_roots: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Work:
    rel_path: str
    size: int
    mtime_ns: int
    existing_id: int | None
    meta: TrackMeta | None = None
    quick_hash: str | None = None
    cover: tuple[str, int, int] | None = None
    moved: bool = False
    skip: bool = False


@dataclass
class Dir:
    rel_dir: str
    files: list[Work]
    images: list[str]
    folder_cover: tuple[str, int, int] | None = None


def quick_hash(path: str, size: int) -> str:
    """Size + first and last 64 KiB. Cheap on network shares, good enough to recognise a move."""
    h = xxhash.xxh3_128()
    h.update(size.to_bytes(8, "little"))
    with open(path, "rb") as f:
        h.update(f.read(_HASH_CHUNK))
        if size > 2 * _HASH_CHUNK:
            f.seek(-_HASH_CHUNK, os.SEEK_END)
            h.update(f.read(_HASH_CHUNK))
        elif size > _HASH_CHUNK:
            h.update(f.read())
    return h.hexdigest()


def read_file(root_path: str, rel_path: str, size: int) -> tuple[str | None, TrackMeta | None]:
    """Quick hash + tags of one file. Runs in a reader process; (None, None) if unreadable."""
    path = os.path.join(root_path, rel_path)
    try:
        digest = quick_hash(path, size)
    except OSError:
        return None, None
    try:
        meta = read_track(path)
    except Exception as exc:  # read_track should not raise; never let one file stop a scan
        meta = TrackMeta(error=f"{type(exc).__name__}: {exc}"[:300])
    return digest, meta


def genre_id(conn: Connection, cache: dict[str, int], name: str) -> int:
    """Id of a normalized genre, created on first use."""
    slug = genre_norm.slug(name)
    cached = cache.get(slug)
    if cached is None:
        cached = conn.execute(select(genres.c.id).where(genres.c.slug == slug)).scalar()
        if cached is None:
            cached = conn.execute(genres.insert().values(name=name, slug=slug)).inserted_primary_key[0]
        cache[slug] = cached
    return cached


def refresh_genre_counts(conn: Connection) -> None:
    """Visible tracks per genre; genres nobody uses any more are dropped."""
    conn.execute(
        text(
            "UPDATE genres SET track_count = (SELECT count(*) FROM track_genres tg"
            " JOIN tracks t ON t.id = tg.track_id WHERE tg.genre_id = genres.id AND t.missing_since IS NULL)"
        )
    )
    conn.execute(
        text("DELETE FROM genres WHERE NOT EXISTS (SELECT 1 FROM track_genres tg WHERE tg.genre_id = genres.id)")
    )


_ARTIST_AGG = """
    UPDATE artists SET
      track_count = (SELECT count(*) FROM track_artists ta JOIN tracks t ON t.id = ta.track_id
                     WHERE ta.artist_id = artists.id AND t.missing_since IS NULL),
      album_count = (SELECT count(*) FROM albums a WHERE a.album_artist_id = artists.id AND a.track_count > 0),
      cover_id = coalesce(image_id, CASE WHEN :album_covers = 1 THEN (SELECT a.cover_id FROM albums a
                  WHERE a.album_artist_id = artists.id AND a.cover_id IS NOT NULL AND a.track_count > 0
                  ORDER BY a.year DESC, a.id DESC LIMIT 1) END)
"""


def refresh_artists(conn: Connection, ids: set[int] | None = None) -> None:
    """Counts and image of the artists (all with `ids` None). The image is the artist's own
    picture, else, if the server setting allows it, the cover of the newest album."""
    album_covers = int(server_setting(conn, "artist_album_covers") == "on")
    if ids is None:
        conn.execute(text(_ARTIST_AGG), {"album_covers": album_covers})
        return
    stmt = text(_ARTIST_AGG + " WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
    for chunk in _chunks(sorted(ids)):
        conn.execute(stmt, {"ids": chunk, "album_covers": album_covers})


def _artist_image(names: list[str]) -> str | None:
    """artist.jpg / artist.png / ... among a folder's images (any case), best format first."""
    by_ext = {}
    for n in names:
        stem, _, ext = n.rpartition(".")
        if stem.lower() == ARTIST_IMAGE_STEM:
            by_ext.setdefault(ext.lower(), n)
    return next((by_ext[e] for e in ARTIST_IMAGE_EXTENSIONS if e in by_ext), None)


def _chunks(items: list, n: int = _CHUNK) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


class _NoContext:
    def progress(self, *_a, **_k) -> None:
        pass

    def should_stop(self) -> bool:
        return False


class Scanner:
    def __init__(self, db: Database, settings: Settings, cover_store: CoverStore, ctx=None) -> None:
        self.db = db
        self.settings = settings
        self.covers = cover_store
        self.ctx = ctx or _NoContext()
        self.stats = ScanStats()
        self._artist_ids: dict[str, int] = {}
        self._album_ids: dict[str, int] = {}
        self._cover_ids: dict[str, int] = {}
        self._genre_ids: dict[str, int] = {}
        self._root_paths: dict[int, str] = {}
        self._estimate = 0
        self._pool: ThreadPoolExecutor | None = None
        self._readers: ProcessPoolExecutor | None = None

    # --- entry point ---------------------------------------------------------------------

    def run(self, root_ids: list[int] | None = None, force: bool = False) -> ScanStats:
        with self.db.read() as conn:
            all_roots = conn.execute(select(library_roots).order_by(library_roots.c.path)).all()
        self._root_paths = {r.id: r.path for r in all_roots}
        roots = [r for r in all_roots if r.enabled and (root_ids is None or r.id in root_ids)]
        self._estimate = sum(r.track_count for r in roots)
        self.stats.roots = len(roots)
        log.info("scan.started", roots=len(roots), force=force)
        workers = max(1, self.settings.scan_workers)
        # Tags are read in separate processes: mutagen does many small reads, and with threads
        # every read waits for the GIL again (convoy effect, ~50x slower than one thread).
        # Cover resizing stays in threads, Pillow releases the GIL and needs the shared de-dup.
        readers = (
            ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("forkserver"))
            if workers > 1
            else None
        )
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                self._pool = pool
                self._readers = readers
                for root in roots:
                    self._scan_root(root, force)
                    if self.ctx.should_stop():
                        break
        finally:
            if readers is not None:
                readers.shutdown(cancel_futures=True)
        if not self.ctx.should_stop():
            self.finalize()
        log.info("scan.finished", **self.stats.as_dict(), interrupted=self.ctx.should_stop())
        return self.stats

    # --- per root ------------------------------------------------------------------------

    def _scan_root(self, root, force: bool) -> None:
        root_path = Path(root.path)
        if not root_path.is_dir():
            self._set_root_status(root.id, "offline", "folder not found (not mounted?)")
            self.stats.offline_roots.append(root.path)
            return
        with self.db.read() as conn:
            excludes = {
                r.rel_path
                for r in conn.execute(select(library_excludes.c.rel_path).where(library_excludes.c.root_id == root.id))
            }
            known = conn.execute(
                select(tracks.c.id).where(tracks.c.root_id == root.id, tracks.c.missing_since.is_(None)).limit(1)
            ).first()
        first_scan = root.status == "new"
        seen: set[int] = set()
        restore: list[int] = []
        pending: list[Dir] = []
        pending_files = 0
        files_in_root = 0
        artist_images: dict[str, str] = {}  # rel_dir -> artist image file name

        for rel_dir, files, images in iter_dirs(root_path, excludes):
            if self.ctx.should_stop():
                break
            files_in_root += len(files)
            self.stats.files_seen += len(files)
            if images and (name := _artist_image(images)):
                artist_images[rel_dir] = name
            if not files:
                continue
            existing = self._existing(root.id, rel_dir, files)
            changed: list[Work] = []
            for name, size, mtime_ns in files:
                rel = f"{rel_dir}/{name}" if rel_dir else name
                ex = existing.get(rel)
                if ex is not None:
                    seen.add(ex.id)
                    if not force and ex.size == size and ex.mtime_ns == mtime_ns:
                        self.stats.unchanged += 1
                        if ex.missing_since is not None:
                            restore.append(ex.id)
                        continue
                changed.append(Work(rel, size, mtime_ns, ex.id if ex else None))
            if changed:
                pending.append(Dir(rel_dir, changed, images))
                pending_files += len(changed)
            self.ctx.progress(
                self.stats.files_seen,
                max(self._estimate, self.stats.files_seen),
                f"{root.path}/{rel_dir}" if rel_dir else root.path,
            )
            if pending_files >= BATCH_FILES or len(restore) >= _RESTORE_BATCH:
                self._flush(root, root_path, pending, restore, seen, first_scan)
                pending, restore, pending_files = [], [], 0
        self._flush(root, root_path, pending, restore, seen, first_scan)

        if self.ctx.should_stop():
            return
        if files_in_root == 0 and known is not None:
            self._set_root_status(root.id, "offline", "folder is empty (not mounted?), keeping its tracks")
            self.stats.offline_roots.append(root.path)
            return
        self._mark_missing(root.id, seen)
        with self.db.write() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM tracks WHERE root_id = :r AND missing_since IS NULL"),
                {"r": root.id},
            ).scalar_one()
            conn.execute(
                update(library_roots)
                .where(library_roots.c.id == root.id)
                .values(status="online", status_message=None, last_scan_at=now_ms(), track_count=count)
            )
        self._scan_artist_images(root.id, root_path, artist_images, force)

    def _existing(self, root_id: int, rel_dir: str, files) -> dict:
        rels = [f"{rel_dir}/{n}" if rel_dir else n for n, _, _ in files]
        out = {}
        with self.db.read() as conn:
            for chunk in _chunks(rels):
                rows = conn.execute(
                    select(
                        tracks.c.id,
                        tracks.c.rel_path,
                        tracks.c.size,
                        tracks.c.mtime_ns,
                        tracks.c.missing_since,
                    ).where(tracks.c.root_id == root_id, tracks.c.rel_path.in_(chunk))
                )
                out.update({r.rel_path: r for r in rows})
        return out

    def _set_root_status(self, root_id: int, status: str, message: str | None) -> None:
        if status == "offline":
            log.warning("scan.root_offline", root_id=root_id, reason=message)
        with self.db.write() as conn:
            conn.execute(
                update(library_roots)
                .where(library_roots.c.id == root_id)
                .values(status=status, status_message=message, last_scan_at=now_ms())
            )

    def _mark_missing(self, root_id: int, seen: set[int]) -> None:
        with self.db.read() as conn:
            present = [
                r.id
                for r in conn.execute(
                    select(tracks.c.id).where(tracks.c.root_id == root_id, tracks.c.missing_since.is_(None))
                )
            ]
        gone = [i for i in present if i not in seen]
        if not gone:
            return
        ts = now_ms()
        albums_set: set[int] = set()
        artists_set: set[int] = set()
        with self.db.write() as conn:
            self._remember_old_refs(conn, gone, albums_set, artists_set)
            for chunk in _chunks(gone):
                conn.execute(update(tracks).where(tracks.c.id.in_(chunk)).values(missing_since=ts))
            self._refresh_albums(conn, albums_set)
            self._refresh_artists(conn, artists_set)
            bump_library_generation(conn)
        self.stats.missing += len(gone)

    # --- reading files -------------------------------------------------------------------

    def _map(self, fn, *iterables):
        """map() over the reader processes, or in-process when there is only one worker.
        Chunks are sized so every process gets work (renders are few but expensive)."""
        if self._readers is None:
            return map(fn, *iterables)
        items = len(iterables[0])
        chunk = max(1, items // (self.settings.scan_workers * 4))
        return self._readers.map(fn, *iterables, chunksize=chunk)

    def _read_files(self, root_path: Path, dirs: list[Dir]) -> None:
        works = [w for d in dirs for w in d.files]
        args = ([str(root_path)] * len(works), [w.rel_path for w in works], [w.size for w in works])
        for w, (digest, meta) in zip(works, self._map(read_file, *args), strict=True):
            if digest is None:
                w.skip = True  # vanished or unreadable since the walk; the next scan sees it again
            else:
                w.quick_hash, w.meta = digest, meta
        pictures = [w.meta.picture if w.meta is not None else None for w in works]
        for w, cover in zip(works, self.covers.ingest_many(pictures, self._map), strict=True):
            w.cover = cover
            if w.meta is not None:
                w.meta.picture = None  # free memory before the batch is written

        # Folder images (cover.jpg, ...): read in threads (I/O), render as one batch.
        cover_dirs = [d for d in dirs if d.images or is_disc_dir(PurePosixPath(d.rel_dir).name) is not None]
        images = list(self._pool.map(lambda d: self._folder_image(root_path, d), cover_dirs))
        for d, cover in zip(cover_dirs, self.covers.ingest_many(images, self._map), strict=True):
            d.folder_cover = cover

    def _folder_image(self, root_path: Path, d: Dir) -> bytes | None:
        directory = root_path / d.rel_dir if d.rel_dir else root_path
        data = self._read_folder_image(directory, d.images)
        if data is None and d.rel_dir and is_disc_dir(PurePosixPath(d.rel_dir).name) is not None:
            try:  # CD1/, Disc 2/: the cover usually sits in the album folder above
                names = [e.name for e in os.scandir(directory.parent) if e.is_file()]
            except OSError:
                names = []
            data = self._read_folder_image(directory.parent, names)
        return data

    @staticmethod
    def _read_folder_image(directory: Path, names: list[str]) -> bytes | None:
        by_stem: dict[str, str] = {}
        for n in names:
            stem, _, ext = n.rpartition(".")
            if stem.lower() == ARTIST_IMAGE_STEM:
                continue  # the artist's picture, even when it is the only image in an album folder
            if ext.lower() in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
                by_stem.setdefault(stem.lower(), n)
        candidates = [by_stem[s] for s in FOLDER_COVER_NAMES if s in by_stem]
        if not candidates and len(by_stem) == 1:
            candidates = list(by_stem.values())  # a single image in an album folder is the cover
        for name in candidates:
            try:
                return (directory / name).read_bytes()
            except OSError:
                continue
        return None

    # --- artist images -------------------------------------------------------------------

    def _scan_artist_images(self, root_id: int, root_path: Path, found: dict[str, str], force: bool) -> None:
        """artist.jpg/.png after a complete walk of a root. It belongs to the album artist of the
        albums in the folders below (Artist/Album/), or, for flat layouts, sits in an album folder.
        Artist folders hold no audio, so this cannot happen per batch. Files are read only when
        new or changed; an image this root no longer has is dropped."""
        album_dirs: dict[int, set[str]] = {}
        with self.db.read() as conn:
            for r in conn.execute(
                select(albums.c.album_artist_id, tracks.c.rel_path)
                .join(albums, albums.c.id == tracks.c.album_id)
                .where(tracks.c.root_id == root_id, tracks.c.missing_since.is_(None))
            ):
                track_dir = str(PurePosixPath(r.rel_path).parent)
                album_dir = album_dir_of("" if track_dir == "." else track_dir)
                if album_dir:  # tracks right in the root have no artist folder
                    album_dirs.setdefault(r.album_artist_id, set()).add(album_dir)
            current = {
                r.id: r.image_key
                for r in conn.execute(select(artists.c.id, artists.c.image_key).where(artists.c.image_key.is_not(None)))
            }
        keys: dict[int, tuple[str, str]] = {}  # artist id -> (rel path, image key)
        for artist_id, dirs in album_dirs.items():
            parents = sorted({p for d in dirs if (p := str(PurePosixPath(d).parent)) != "."})
            folder = next((p for p in parents if p in found), None)
            if folder is None:
                folder = next((d for d in sorted(dirs) if d in found), None)
            if folder is None:
                continue
            rel = f"{folder}/{found[folder]}"
            try:
                st = (root_path / rel).stat()
            except OSError:
                continue
            keys[artist_id] = (rel, f"{root_id}:{rel}:{st.st_size}:{st.st_mtime_ns}")
        prefix = f"{root_id}:"
        todo = [a for a, (_rel, key) in keys.items() if force or current.get(a) != key]
        gone = [a for a, key in current.items() if key.startswith(prefix) and a not in keys]
        if not todo and not gone:
            return

        def read(artist_id: int) -> bytes | None:
            try:
                return (root_path / keys[artist_id][0]).read_bytes()
            except OSError:
                return None

        images = list(self._pool.map(read, todo)) if self._pool else [read(a) for a in todo]
        rendered = self.covers.ingest_many(images, self._map)
        with self.db.write() as conn:
            for artist_id, cover in zip(todo, rendered, strict=True):
                # An unreadable image keeps its key, so it is not retried until the file changes.
                image_id = self._cover_id(conn, cover, "artist") if cover else None
                conn.execute(
                    update(artists)
                    .where(artists.c.id == artist_id)
                    .values(image_id=image_id, image_key=keys[artist_id][1])
                )
            for chunk in _chunks(gone):
                conn.execute(update(artists).where(artists.c.id.in_(chunk)).values(image_id=None, image_key=None))
            self._refresh_artists(conn, set(todo) | set(gone))
            bump_library_generation(conn)
        log.info("scan.artist_images", root_id=root_id, updated=len(todo), removed=len(gone))

    # --- writing a batch -----------------------------------------------------------------

    def _flush(
        self, root, root_path: Path, dirs: list[Dir], restore: list[int], seen: set[int], first_scan: bool
    ) -> None:
        if not dirs and not restore:
            return
        works = [w for d in dirs for w in d.files]
        self._read_files(root_path, dirs)
        self._detect_moves(root.id, [w for w in works if w.existing_id is None and not w.skip])
        self.write_batch(root.id, dirs, restore, first_scan)
        for w in works:
            if w.existing_id:
                seen.add(w.existing_id)

    def write_batch(self, root_id: int, dirs: list[Dir], restore: list[int], first_scan: bool) -> None:
        """One transaction: restored ids + prepared directories, then the affected aggregates."""
        works = [w for d in dirs for w in d.files]
        touched_albums: set[int] = set()
        touched_artists: set[int] = set()
        with self.db.write() as conn:
            for chunk in _chunks(restore):
                conn.execute(update(tracks).where(tracks.c.id.in_(chunk)).values(missing_since=None))
            self.stats.restored += len(restore)
            # Restored tracks and tracks that change: their previous album/artists need new counts too.
            self._remember_old_refs(
                conn,
                restore + [w.existing_id for w in works if w.existing_id],
                touched_albums,
                touched_artists,
            )
            for d in dirs:
                self._write_dir(conn, root_id, d, first_scan, touched_albums, touched_artists)
            self._refresh_albums(conn, touched_albums)
            for chunk in _chunks(sorted(touched_albums)):
                touched_artists.update(
                    r[0] for r in conn.execute(select(albums.c.album_artist_id).where(albums.c.id.in_(chunk)))
                )
            self._refresh_artists(conn, touched_artists)
            bump_library_generation(conn)

    def _detect_moves(self, root_id: int, new_works: list[Work]) -> None:
        if not new_works:
            return
        claimed: set[int] = set()
        with self.db.read() as conn:
            for w in new_works:
                if w.quick_hash is None:
                    continue
                candidates = conn.execute(
                    select(tracks.c.id, tracks.c.root_id, tracks.c.rel_path).where(
                        tracks.c.quick_hash == w.quick_hash, tracks.c.size == w.size
                    )
                ).all()
                for c in candidates:
                    if c.id in claimed:
                        continue
                    old_root = self._root_paths.get(c.root_id)
                    if old_root and os.path.exists(os.path.join(old_root, c.rel_path)):
                        continue  # a copy, not a move
                    w.existing_id = c.id
                    w.moved = True
                    claimed.add(c.id)
                    break

    def _remember_old_refs(self, conn: Connection, ids: list[int], albums_set: set[int], artists_set: set[int]):
        """Albums/artists a changed track belonged to before; their counts change too."""
        for chunk in _chunks(ids):
            for r in conn.execute(select(tracks.c.album_id).where(tracks.c.id.in_(chunk))):
                albums_set.add(r.album_id)
            for r in conn.execute(select(track_artists.c.artist_id).where(track_artists.c.track_id.in_(chunk))):
                artists_set.add(r.artist_id)

    def _write_dir(
        self,
        conn: Connection,
        root_id: int,
        d: Dir,
        first_scan: bool,
        touched_albums: set[int],
        touched_artists: set[int],
    ) -> None:
        files = [w for w in d.files if not w.skip]
        resolved = [self._resolve(root_id, d, w) for w in files]
        # Untagged albums (no album artist): one album artist if all tracks agree, else "Various Artists".
        dir_artists: dict[str, set[str]] = {}
        for r in resolved:
            if r["album_artist"] is None:
                dir_artists.setdefault(r["group_key"], set()).add(norm(r["artists"][0]))
        ts = now_ms()
        new_rows: list[dict] = []
        inserted: list[tuple] = []
        updated: list[tuple] = []
        for w, r in zip(files, resolved, strict=True):
            album_artist = r["album_artist"]
            if album_artist is None:
                album_artist = r["artists"][0] if len(dir_artists[r["group_key"]]) == 1 else VARIOUS_ARTISTS
            album_artist_id = self._artist_id(conn, album_artist, r["mb_album_artist_id"])
            album_id = self._album_id(conn, r, album_artist, album_artist_id, ts)
            artist_ids = [
                self._artist_id(conn, name, r["mb_artist_id"] if len(r["artists"]) == 1 else None)
                for name in r["artists"]
            ]
            # (artist id, role) per track_artists row; a guest who is also a main artist counts once
            credits = [(aid, "main") for aid in dict.fromkeys(artist_ids)]
            credits += [
                (aid, "feat")
                for aid in dict.fromkeys(self._artist_id(conn, name, None) for name in r["featured"])
                if aid not in artist_ids
            ]
            cover_id = None
            cover = w.cover or d.folder_cover
            if cover:
                cover_id = self._cover_id(conn, cover, "embedded" if w.cover else "folder")
            meta = w.meta
            values = {
                "root_id": root_id,
                "rel_path": w.rel_path,
                "size": w.size,
                "mtime_ns": w.mtime_ns,
                "quick_hash": w.quick_hash,
                "container": meta.container,
                "codec": meta.codec,
                "bitrate": meta.bitrate,
                "sample_rate": meta.sample_rate,
                "bit_depth": meta.bit_depth,
                "channels": meta.channels,
                "duration_ms": meta.duration_ms,
                "title": r["title"],
                "title_sort": norm(r["title"]),
                "artist_name": r["artist_display"],
                "artist_id": artist_ids[0],
                "album_id": album_id,
                "track_no": r["track_no"],
                "disc_no": r["disc_no"],
                "year": r["year"] or 0,
                "date": meta.date,
                "genre_raw": "; ".join(meta.genres) or None,
                "cover_id": cover_id,
                "mb_track_id": meta.mb_track_id,
                "mb_recording_id": meta.mb_recording_id,
                "rg_track_gain": meta.rg_track_gain,
                "rg_track_peak": meta.rg_track_peak,
                "rg_album_gain": meta.rg_album_gain,
                "rg_album_peak": meta.rg_album_peak,
                "tag_status": r["tag_status"],
                "missing_since": None,
                "updated_at": ts,
            }
            if w.existing_id:
                conn.execute(update(tracks).where(tracks.c.id == w.existing_id).values(**values))
                if w.moved:
                    self.stats.moved += 1
                else:
                    self.stats.updated += 1
                updated.append((w, r, credits))
            else:
                values["added_at"] = min(ts, w.mtime_ns // 1_000_000) if first_scan else ts
                new_rows.append(values)
                inserted.append((w, r, credits))
            if r["tag_status"] == "error":
                self.stats.errors += 1
            touched_albums.add(album_id)
            touched_artists.update(aid for aid, _role in credits)
            touched_artists.add(album_artist_id)

        # New tracks in one multi-row INSERT .. RETURNING (ids come back in parameter order).
        if new_rows:
            result = conn.execute(tracks.insert().returning(tracks.c.id, sort_by_parameter_order=True), new_rows)
            for (w, _r, _a), row in zip(inserted, result, strict=True):
                w.existing_id = row.id
                self.stats.added += 1
        changed_ids = [w.existing_id for w, _r, _a in updated]
        for chunk in _chunks(changed_ids):
            conn.execute(track_artists.delete().where(track_artists.c.track_id.in_(chunk)))
        done = inserted + updated
        if not done:
            return
        conn.execute(
            track_artists.insert(),
            [
                {"track_id": w.existing_id, "artist_id": aid, "role": role, "position": i}
                for w, _r, track_credits in done
                for i, (aid, role) in enumerate(track_credits)
            ],
        )
        if changed_ids:
            search.remove_tracks(conn, changed_ids)
        search.add_tracks(conn, [(w.existing_id, r["title"], r["artist_display"], r["album"]) for w, r, _a in done])
        for chunk in _chunks(changed_ids):
            conn.execute(track_genres.delete().where(track_genres.c.track_id.in_(chunk)))
        genre_rows = [
            {"track_id": w.existing_id, "genre_id": self.genre_id(conn, name)}
            for w, _r, _a in done
            for name in genre_norm.normalize(w.meta.genres)
        ]
        if genre_rows:
            conn.execute(track_genres.insert(), genre_rows)

    def genre_id(self, conn: Connection, name: str) -> int:
        return genre_id(conn, self._genre_ids, name)

    def _resolve(self, root_id: int, d: Dir, w: Work) -> dict:
        """Tags first, then the path for whatever is missing."""
        meta = w.meta
        pi = from_path(w.rel_path)
        artists_list = meta.artists or ([pi.artist] if pi.artist else []) or [UNKNOWN_ARTIST]
        title = meta.title or pi.title
        album = meta.album or pi.album or UNKNOWN_ALBUM
        album_artist = meta.album_artists[0] if meta.album_artists else None
        if album_artist is None and meta.compilation:
            album_artist = VARIOUS_ARTISTS
        if meta.mb_release_id:
            group_key = f"mb:{meta.mb_release_id.lower()}"
        elif album_artist:
            group_key = f"aa:{norm(album_artist)}\x1f{norm(album)}"
        else:
            group_key = f"dir:{root_id}:{album_dir_of(d.rel_dir)}\x1f{norm(album)}"
        if meta.error and not meta.has_tags:
            status = "error"
        elif not meta.has_tags:
            status = "fallback"
        elif meta.title and meta.artists and meta.album:
            status = "ok"
        else:
            status = "partial"
        return {
            "title": title,
            "artists": artists_list,
            "featured": meta.featured_artists,
            "artist_display": meta.artist_display or ", ".join(artists_list),
            "album": album,
            "album_artist": album_artist,
            "group_key": group_key,
            "track_no": meta.track_no or pi.track_no,
            "disc_no": meta.disc_no or pi.disc_no,
            "year": meta.year or pi.album_year,
            "compilation": meta.compilation or album_artist == VARIOUS_ARTISTS,
            "mb_release_id": meta.mb_release_id,
            "mb_artist_id": meta.mb_artist_id,
            "mb_album_artist_id": meta.mb_album_artist_id,
            "tag_status": status,
        }

    # --- get-or-create helpers (this process is the only writer of these tables) ---------

    def _artist_id(self, conn: Connection, name: str, mbid: str | None) -> int:
        key = norm(name) or norm(UNKNOWN_ARTIST)
        cached = self._artist_ids.get(key)
        if cached is not None:
            return cached
        row = conn.execute(select(artists.c.id).where(artists.c.name_norm == key)).first()
        if row is not None:
            artist_id = row.id
        else:
            artist_id = conn.execute(
                artists.insert().values(
                    name=name,
                    name_sort=sort_key(name, self.settings.articles),
                    name_norm=key,
                    mb_artist_id=mbid,
                    created_at=now_ms(),
                )
            ).inserted_primary_key[0]
            search.index_artist(conn, artist_id, name)
        self._artist_ids[key] = artist_id
        return artist_id

    def _album_id(self, conn: Connection, r: dict, album_artist: str, album_artist_id: int, ts: int) -> int:
        key = r["group_key"]
        cached = self._album_ids.get(key)
        if cached is not None:
            return cached
        row = conn.execute(select(albums.c.id).where(albums.c.group_key == key)).first()
        if row is not None:
            album_id = row.id
        else:
            album_id = conn.execute(
                albums.insert().values(
                    group_key=key,
                    title=r["album"],
                    title_sort=norm(r["album"]),
                    album_artist_id=album_artist_id,
                    artist_sort=sort_key(album_artist, self.settings.articles),
                    year=r["year"] or 0,
                    compilation=r["compilation"],
                    mb_release_id=r["mb_release_id"],
                    added_at=ts,
                    created_at=ts,
                )
            ).inserted_primary_key[0]
            search.index_album(conn, album_id, r["album"], album_artist)
        self._album_ids[key] = album_id
        return album_id

    def _cover_id(self, conn: Connection, cover: tuple[str, int, int], source: str) -> int:
        digest, width, height = cover
        cached = self._cover_ids.get(digest)
        if cached is not None:
            return cached
        row = conn.execute(select(covers.c.id).where(covers.c.hash == digest)).first()
        if row is not None:
            cover_id = row.id
        else:
            cover_id = conn.execute(
                covers.insert().values(hash=digest, source=source, width=width, height=height, created_at=now_ms())
            ).inserted_primary_key[0]
            self.stats.covers_added += 1
        self._cover_ids[digest] = cover_id
        return cover_id

    # --- aggregates ----------------------------------------------------------------------

    _ALBUM_AGG = """
        UPDATE albums SET
          track_count = (SELECT count(*) FROM tracks t WHERE t.album_id = albums.id AND t.missing_since IS NULL),
          duration_ms = (SELECT coalesce(sum(t.duration_ms), 0) FROM tracks t
                         WHERE t.album_id = albums.id AND t.missing_since IS NULL),
          year = coalesce((SELECT max(t.year) FROM tracks t
                           WHERE t.album_id = albums.id AND t.missing_since IS NULL), 0),
          added_at = coalesce((SELECT min(t.added_at) FROM tracks t WHERE t.album_id = albums.id), albums.added_at),
          cover_id = (SELECT t.cover_id FROM tracks t
                      WHERE t.album_id = albums.id AND t.cover_id IS NOT NULL AND t.missing_since IS NULL
                      ORDER BY coalesce(t.disc_no, 0), coalesce(t.track_no, 0), t.id LIMIT 1)
    """
    _PLAYLIST_AGG = """
        UPDATE playlists SET
          item_count = (SELECT count(*) FROM playlist_items i WHERE i.playlist_id = playlists.id),
          duration_ms = (SELECT coalesce(sum(t.duration_ms), 0) FROM playlist_items i
                         JOIN tracks t ON t.id = i.track_id WHERE i.playlist_id = playlists.id),
          version = version + 1
    """

    def _refresh_albums(self, conn: Connection, ids: set[int] | None) -> None:
        if ids is None:
            conn.execute(text(self._ALBUM_AGG))
            return
        stmt = text(self._ALBUM_AGG + " WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
        for chunk in _chunks(sorted(ids)):
            conn.execute(stmt, {"ids": chunk})

    def _refresh_artists(self, conn: Connection, ids: set[int] | None) -> None:
        refresh_artists(conn, ids)

    # --- end of a complete scan ----------------------------------------------------------

    def finalize(self) -> None:
        """End of a complete scan: purge expired missing tracks, drop orphans, recompute counts."""
        grace_ms = self.settings.missing_grace_days * 86_400_000
        cutoff = now_ms() - grace_ms
        with self.db.write() as conn:
            purge = [
                r[0]
                for r in conn.execute(
                    select(tracks.c.id)
                    .join(library_roots, library_roots.c.id == tracks.c.root_id)
                    .where(
                        tracks.c.missing_since.is_not(None),
                        tracks.c.missing_since < cutoff,
                        library_roots.c.enabled.is_(True),
                        library_roots.c.status == "online",
                    )
                )
            ]
            for chunk in _chunks(purge):
                search.remove_tracks(conn, chunk)
                conn.execute(tracks.delete().where(tracks.c.id.in_(chunk)))
            self.stats.purged = len(purge)
            if purge:
                # Their playlist entries went with them (ON DELETE CASCADE); refresh cached stats.
                conn.execute(text(self._PLAYLIST_AGG))

            empty_albums = [
                r[0]
                for r in conn.execute(
                    text("SELECT id FROM albums WHERE NOT EXISTS (SELECT 1 FROM tracks t WHERE t.album_id = albums.id)")
                )
            ]
            for chunk in _chunks(empty_albums):
                search.remove_albums(conn, chunk)
                conn.execute(albums.delete().where(albums.c.id.in_(chunk)))
            self._refresh_albums(conn, None)
            self._refresh_artists(conn, None)
            refresh_genre_counts(conn)
            self._genre_ids.clear()
            orphan_artists = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT id FROM artists"
                        " WHERE NOT EXISTS (SELECT 1 FROM track_artists ta WHERE ta.artist_id = artists.id)"
                        " AND NOT EXISTS (SELECT 1 FROM albums a WHERE a.album_artist_id = artists.id)"
                        " AND NOT EXISTS (SELECT 1 FROM tracks t WHERE t.artist_id = artists.id)"
                    )
                )
            ]
            for chunk in _chunks(orphan_artists):
                search.remove_artists(conn, chunk)
                conn.execute(artists.delete().where(artists.c.id.in_(chunk)))
            orphan_covers = conn.execute(
                text(
                    # NOT IN builds the set of used ids once. A correlated NOT EXISTS would scan
                    # all tracks per cover (no index on cover_id): minutes at 100k tracks.
                    "SELECT id, hash FROM covers WHERE id NOT IN ("
                    " SELECT cover_id FROM tracks WHERE cover_id IS NOT NULL"
                    " UNION SELECT cover_id FROM albums WHERE cover_id IS NOT NULL"
                    " UNION SELECT cover_id FROM artists WHERE cover_id IS NOT NULL"
                    " UNION SELECT image_id FROM artists WHERE image_id IS NOT NULL"
                    " UNION SELECT cover_id FROM playlists WHERE cover_id IS NOT NULL)"
                )
            ).all()
            for chunk in _chunks(orphan_covers):
                conn.execute(covers.delete().where(covers.c.id.in_([c.id for c in chunk])))
            bump_library_generation(conn)
        # Files only after the commit: a rolled-back transaction must not lose images.
        for c in orphan_covers:
            self.covers.delete(c.hash)
        if self.db.is_sqlite:
            # Refresh planner statistics after large changes (cheap, recommended by SQLite).
            with self.db.engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA optimize")
        self._artist_ids.clear()
        self._album_ids.clear()
        self._cover_ids.clear()
