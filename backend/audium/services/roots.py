"""Library root folders. Only paths inside the mounted music directory are allowed:
the container cannot see anything else, so the UI only ever browses below AUDIUM_MUSIC_DIR."""

import os
from pathlib import Path, PurePosixPath

from sqlalchemy import Connection, func, select, update

from audium.config import Settings
from audium.db.schema import library_excludes, library_roots, tracks
from audium.errors import BadRequest, Conflict, NotFound
from audium.logging import get_logger
from audium.scanner.formats import IGNORED_DIRS
from audium.util import now_ms

log = get_logger(__name__)
_BROWSE_LIMIT = 1000


def _music_root(settings: Settings) -> Path:
    return Path(os.path.realpath(settings.music_dir))


def resolve_inside_music(settings: Settings, path: str) -> Path:
    """Absolute, symlink-free path that must lie inside the music dir."""
    music = _music_root(settings)
    raw = Path(path)
    candidate = raw if raw.is_absolute() else music / raw
    real = Path(os.path.realpath(candidate))
    if real != music and music not in real.parents:
        raise BadRequest(f"path must be inside {settings.music_dir}")
    return real


def list_roots(conn: Connection):
    excl = select(library_excludes.c.root_id, func.count().label("n")).group_by(library_excludes.c.root_id).subquery()
    return conn.execute(
        select(library_roots, func.coalesce(excl.c.n, 0).label("exclude_count"))
        .outerjoin(excl, excl.c.root_id == library_roots.c.id)
        .order_by(library_roots.c.path)
    ).all()


def get_root(conn: Connection, root_id: int):
    row = conn.execute(select(library_roots).where(library_roots.c.id == root_id)).first()
    if row is None:
        raise NotFound("library folder not found")
    return row


def add_root(conn: Connection, settings: Settings, path: str):
    real = resolve_inside_music(settings, path)
    if not real.is_dir():
        raise BadRequest("path is not a directory")
    for row in conn.execute(select(library_roots.c.path)).all():
        other = Path(row.path)
        if other == real or other in real.parents or real in other.parents:
            raise Conflict(f"overlaps with existing library folder {row.path}")
    root_id = conn.execute(
        library_roots.insert().values(path=str(real), enabled=True, status="new", created_at=now_ms())
    ).inserted_primary_key[0]
    log.info("library.root_added", root_id=root_id, path=str(real))
    return get_root(conn, root_id)


def set_enabled(conn: Connection, root_id: int, enabled: bool):
    get_root(conn, root_id)
    conn.execute(update(library_roots).where(library_roots.c.id == root_id).values(enabled=enabled))
    if not enabled:
        # Hidden right away; kept (not purged) while disabled, so re-enabling restores everything.
        conn.execute(
            update(tracks)
            .where(tracks.c.root_id == root_id, tracks.c.missing_since.is_(None))
            .values(missing_since=now_ms())
        )
    return get_root(conn, root_id)


def list_excludes(conn: Connection, root_id: int):
    get_root(conn, root_id)
    return conn.execute(
        select(library_excludes).where(library_excludes.c.root_id == root_id).order_by(library_excludes.c.rel_path)
    ).all()


def add_exclude(conn: Connection, settings: Settings, root_id: int, rel_path: str):
    root = get_root(conn, root_id)
    rel = PurePosixPath(rel_path.strip().strip("/"))
    if not str(rel) or str(rel) == "." or ".." in rel.parts:
        raise BadRequest("rel_path must be a sub-folder of the library folder")
    resolve_inside_music(settings, os.path.join(root.path, str(rel)))
    exists = conn.execute(
        select(library_excludes.c.id).where(
            library_excludes.c.root_id == root_id, library_excludes.c.rel_path == str(rel)
        )
    ).scalar()
    if exists:
        raise Conflict("already excluded")
    exclude_id = conn.execute(
        library_excludes.insert().values(root_id=root_id, rel_path=str(rel))
    ).inserted_primary_key[0]
    return conn.execute(select(library_excludes).where(library_excludes.c.id == exclude_id)).first()


def remove_exclude(conn: Connection, root_id: int, exclude_id: int) -> None:
    res = conn.execute(
        library_excludes.delete().where(library_excludes.c.id == exclude_id, library_excludes.c.root_id == root_id)
    )
    if res.rowcount == 0:
        raise NotFound("exclude not found")


def browse(conn: Connection, settings: Settings, path: str | None):
    """Sub-folders of `path` (default: the music dir) for the folder picker."""
    target = resolve_inside_music(settings, path or str(settings.music_dir))
    if not target.is_dir():
        raise NotFound("folder not found")
    roots = {r.path: r.id for r in conn.execute(select(library_roots.c.path, library_roots.c.id)).all()}
    entries = []
    try:
        with os.scandir(target) as it:
            for e in it:
                if e.name.startswith(".") or e.name.lower() in IGNORED_DIRS:
                    continue
                try:
                    if not e.is_dir():
                        continue
                except OSError:
                    continue
                full = os.path.realpath(e.path)
                entries.append({"name": e.name, "path": full, "root_id": roots.get(full)})
                if len(entries) >= _BROWSE_LIMIT:
                    break
    except PermissionError as exc:
        raise BadRequest("folder is not readable by the container user") from exc
    entries.sort(key=lambda x: x["name"].casefold())
    music = _music_root(settings)
    parent = None if target == music else str(target.parent)
    return {"path": str(target), "parent": parent, "root_id": roots.get(str(target)), "folders": entries}


def discover_initial_roots(conn: Connection, settings: Settings) -> list[str]:
    """On first start: AUDIUM_LIBRARY_ROOTS if given, otherwise every top-level folder of the
    music dir (one root per mount, so an unmounted share is detected as offline instead of
    looking like deleted music). Falls back to the music dir itself."""
    if conn.execute(select(func.count()).select_from(library_roots)).scalar_one() > 0:
        return []
    if settings.library_roots:
        candidates = [p.strip() for p in settings.library_roots.split(",") if p.strip()]
    else:
        music = settings.music_dir
        if not music.is_dir():
            return []
        try:
            subdirs = sorted(
                e.path
                for e in os.scandir(music)
                if e.is_dir() and not e.name.startswith(".") and e.name.lower() not in IGNORED_DIRS
            )
        except OSError:
            subdirs = []
        candidates = subdirs or [str(music)]
    added = []
    for path in candidates:
        try:
            added.append(add_root(conn, settings, path).path)
        except (BadRequest, Conflict) as exc:
            log.warning("library.root_skipped", path=path, reason=exc.message)
    return added
