import os
from collections.abc import Iterator
from pathlib import Path

from audium.logging import get_logger
from audium.scanner.formats import AUDIO_EXTENSIONS, IGNORED_DIRS, IMAGE_EXTENSIONS

log = get_logger(__name__)

FileEntry = tuple[str, int, int]  # name, size, mtime_ns


def _ext(name: str) -> str:
    _, _, ext = name.rpartition(".")
    return ext.lower()


def iter_dirs(root: Path, excludes: set[str]) -> Iterator[tuple[str, list[FileEntry], list[str]]]:
    """Yield (rel_dir, audio files, image names) per directory, depth-first in name order.

    Follows symlinks but never visits the same directory twice (loops, bind mounts).
    Unreadable directories are logged and skipped.
    """
    stack = [""]
    visited: set[tuple[int, int]] = set()
    try:
        st = root.stat()
        visited.add((st.st_dev, st.st_ino))
    except OSError:
        return
    while stack:
        rel = stack.pop()
        path = root / rel if rel else root
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError as exc:
            log.warning("scan.dir_unreadable", path=str(path), error=str(exc))
            continue
        files: list[FileEntry] = []
        images: list[str] = []
        subdirs: list[str] = []
        for e in entries:
            name = e.name
            if name.startswith(".") or name.lower() in IGNORED_DIRS:
                continue
            try:
                if e.is_dir():
                    child = f"{rel}/{name}" if rel else name
                    if child in excludes:
                        continue
                    st = e.stat()
                    key = (st.st_dev, st.st_ino)
                    if key in visited:
                        continue
                    visited.add(key)
                    subdirs.append(child)
                elif e.is_file():
                    ext = _ext(name)
                    if ext in AUDIO_EXTENSIONS:
                        st = e.stat()
                        files.append((name, st.st_size, st.st_mtime_ns))
                    elif ext in IMAGE_EXTENSIONS:
                        images.append(name)
            except OSError:
                continue
        subdirs.sort(reverse=True)  # stack pops the alphabetically first one next
        stack.extend(subdirs)
        files.sort()
        yield rel, files, images
