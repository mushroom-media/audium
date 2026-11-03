"""The first-run dialog: what the container sees of the music, and a trial scan of a folder.

A running container cannot mount anything, so the dialog can only look at what is mounted and say
what is missing. The trial scan writes nothing and has hard limits, so it stays quick on a large
library or a slow share.
"""

import os
import random
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import Connection

from audium.config import Settings
from audium.errors import BadRequest
from audium.scanner.formats import FOLDER_COVER_NAMES
from audium.scanner.tags import read_track
from audium.scanner.tasks import enqueue_scan
from audium.scanner.walk import WalkReport, iter_dirs
from audium.services import auth as auth_service
from audium.services import roots as root_service

_MOUNTINFO = Path("/proc/self/mountinfo")
_NETWORK_FS = frozenset({"cifs", "smb3", "smbfs", "nfs", "nfs4", "9p", "fuse.sshfs", "fuse.rclone"})
# Docker names the volume of a VOLUME line without a mount by a random id; it is easily lost.
_ANONYMOUS_VOLUME = re.compile(r"/volumes/[0-9a-f]{64}/_data$")

_PROBE_WALK_S = 5.0
_PROBE_SAMPLES_S = 3.0
_PROBE_MAX_FILES = 20_000
_PROBE_SAMPLES = 20
_MAX_UNREADABLE_SHOWN = 5


@dataclass(frozen=True)
class Mount:
    path: str
    fstype: str
    read_only: bool
    network: bool
    root: str  # inside the source file system; not always the path on the host, so never shown


def parse_mounts(text: str) -> list[Mount]:
    """/proc/self/mountinfo: id parent dev root mountpoint options [tags...] - fstype source super"""
    mounts = []
    for line in text.splitlines():
        fields = line.split(" ")
        if "-" not in fields or len(fields) < 10:
            continue
        fstype = fields[fields.index("-") + 1]
        mounts.append(
            Mount(
                path=_unescape(fields[4]),
                fstype=fstype,
                read_only="ro" in fields[5].split(","),
                network=fstype in _NETWORK_FS,
                root=_unescape(fields[3]),
            )
        )
    return mounts


def _unescape(field: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def _read_mounts() -> list[Mount] | None:
    try:
        return parse_mounts(_MOUNTINFO.read_text())
    except OSError:
        return None  # not on Linux: nothing to tell


def _is_inside(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def data_persistent(settings: Settings, mounts: list[Mount] | None) -> bool | None:
    """Whether the data folder survives a new container. None: cannot tell."""
    if mounts is None:
        return None
    data = os.path.realpath(settings.data_dir)
    holders = [m for m in mounts if m.path != "/" and _is_inside(data, m.path)]
    if not holders:
        return False
    return not _ANONYMOUS_VOLUME.search(max(holders, key=lambda m: len(m.path)).root)


def status(conn: Connection, settings: Settings) -> dict:
    mounts = _read_mounts()
    music = os.path.realpath(settings.music_dir)
    return {
        "pending": auth_service.setup_pending(conn),
        "admin_from_env": bool(settings.admin_user and settings.admin_password),
        "roots_from_env": bool(settings.library_roots),
        "music_dir": str(settings.music_dir),
        "mounts": [asdict(m) for m in mounts or [] if _is_inside(os.path.realpath(m.path), music)],
        "candidates": root_service.initial_candidates(settings),
        "roots": [{"path": r.path, "track_count": r.track_count} for r in root_service.list_roots(conn)],
        "data_persistent": data_persistent(settings, mounts),
    }


def probe(settings: Settings, path: str) -> dict:
    """A quick look at a folder of the music mount, without touching the database."""
    target = root_service.resolve_inside_music(settings, path)
    if not target.is_dir():
        raise BadRequest("path is not a directory")

    report = WalkReport()
    formats: Counter[str] = Counter()
    audio = size = images = folders = with_music = with_cover = 0
    picks: list[str] = []  # one file per folder, so the samples are not all from one album
    complete = True
    deadline = time.monotonic() + _PROBE_WALK_S
    for rel_dir, files, image_names in iter_dirs(target, set(), report):
        folders += 1
        images += len(image_names)
        if files:
            with_music += 1
            if any(n.rpartition(".")[0].lower() in FOLDER_COVER_NAMES for n in image_names):
                with_cover += 1
            middle = files[len(files) // 2][0]
            picks.append(f"{rel_dir}/{middle}" if rel_dir else middle)
        for name, file_size, _mtime in files:
            audio += 1
            size += file_size
            formats[name.rpartition(".")[2].lower()] += 1
        if audio >= _PROBE_MAX_FILES or time.monotonic() >= deadline:
            complete = False
            break

    samples = _read_samples(target, picks)
    tagged = sum(s["tagged"] for s in samples)
    readable = "" not in report.unreadable
    return {
        "path": str(target),
        "readable": readable,
        "complete": complete,
        "audio_files": audio,
        "size_bytes": size,
        "formats": [{"ext": ext, "count": n} for ext, n in formats.most_common()],
        "image_files": images,
        "other_files": report.other_files,
        "folders": folders,
        "folders_with_music": with_music,
        "folders_with_cover": with_cover,
        "unreadable_folders": len(report.unreadable),
        "unreadable_examples": [p for p in report.unreadable if p][:_MAX_UNREADABLE_SHOWN],
        "samples": samples,
        "warnings": _warnings(audio, images, report, samples, tagged, readable),
        **({} if readable else _owner(target)),
    }


def _read_samples(target: Path, picks: list[str]) -> list[dict]:
    chosen = sorted(random.sample(picks, min(_PROBE_SAMPLES, len(picks))))
    deadline = time.monotonic() + _PROBE_SAMPLES_S
    samples = []
    for rel in chosen:
        if time.monotonic() >= deadline:
            break
        meta = read_track(str(target / rel))
        samples.append(
            {
                "path": rel,
                "title": meta.title,
                "artist": ", ".join(meta.artists) or None,
                "album": meta.album,
                "tagged": bool(meta.title and meta.artists),
            }
        )
    return samples


def _warnings(
    audio: int, images: int, report: WalkReport, samples: list[dict], tagged: int, readable: bool
) -> list[str]:
    """Codes; the dialog words them for the reader."""
    if not readable:
        return ["unreadable"]
    warnings = []
    if audio == 0:
        warnings.append("no_audio")
    elif images + report.other_files > 2 * audio and images + report.other_files >= 20:
        warnings.append("mostly_other_files")
    if samples and tagged * 2 < len(samples):
        warnings.append("few_tags")
    if report.unreadable:
        warnings.append("unreadable_subfolders")
    return warnings


def _owner(target: Path) -> dict:
    try:
        st = target.stat()
    except OSError:
        return {}
    return {
        "owner": f"{st.st_uid}:{st.st_gid}",
        "mode": oct(st.st_mode & 0o777)[2:],
        "container_user": f"{os.getuid()}:{os.getgid()}",
    }


def complete(conn: Connection, settings: Settings, paths: list[str] | None) -> int | None:
    """Ends the dialog: adds the chosen folders and starts the scan. Returns its job. Without a
    choice (`None`: skipped), the scan worker adds the folders it finds, as it always did."""
    auth_service.finish_setup(conn)
    if paths is None:
        return None
    existing = {r.path for r in root_service.list_roots(conn)}
    for path in paths:
        if str(root_service.resolve_inside_music(settings, path)) not in existing:
            root_service.add_root(conn, settings, path)
    return enqueue_scan(conn)
