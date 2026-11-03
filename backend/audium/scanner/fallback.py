"""Metadata from the path when tags are missing: <Artist>/<Album (Year)>/<NN - Title>.ext"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

# "01 - Title", "01. Title", "01 Title", "1-01 Title" (disc-track). A bare number ("1979") is a title.
_TRACK_PREFIX_RE = re.compile(r"^(?:(\d{1,2})[-.](\d{1,3})|(\d{1,3}))(?:\s*[-._]\s*|\s+)(.+)$")
# "CD1", "Disc 2", "CD 03 - Bonus", or just "1"/"02" ("01 - Album" is not: album folders are numbered too)
_DISC_DIR_RE = re.compile(r"^(?:(?:cd|disc|disk|dvd)\s*[-_.]?\s*(\d{1,2})\b|(\d{1,2})$)", re.IGNORECASE)
_DISC_NAME_SPLIT_RE = re.compile(r"^(?:cd|disc|disk|dvd)\s*[-_.]?\s*\d{1,2}\b|^\d{1,2}$", re.IGNORECASE)
# "Album CD01", "Album - Disc 2", "Album (CD 2)", "Album [Disc 2 of 3]": one disc of "Album"
_DISC_SUFFIX_RE = re.compile(
    r"^(.*?)[\s_\-:,.]*[(\[]?\s*(?:cd|disc|disk|dvd)\s*[-_.]?\s*(\d{1,2})(?:\s*(?:of|von|/)\s*\d{1,2})?\s*[)\]]?\s*$",
    re.IGNORECASE,
)
_YEAR_SUFFIX_RE = re.compile(r"^(.*?)[\s_-]*[(\[](\d{4})[)\]]\s*$")
_YEAR_PREFIX_RE = re.compile(r"^(\d{4})\s*[-._]\s*(.+)$")

UNKNOWN_ARTIST = "Unknown Artist"
UNKNOWN_ALBUM = "Unknown Album"
VARIOUS_ARTISTS = "Various Artists"


@dataclass
class PathInfo:
    title: str
    track_no: int | None
    disc_no: int | None
    album: str | None
    album_year: int | None
    artist: str | None
    album_dir: str  # directory that represents the album (parent of a CD1/Disc 2 folder)


def is_disc_dir(name: str) -> int | None:
    m = _DISC_DIR_RE.match(name)
    return int(m.group(1) or m.group(2)) if m else None


def disc_title(name: str) -> str | None:
    """What a disc folder's name says beyond its number: "CD2 - Bonus" -> "Bonus", "CD2" -> None."""
    return _DISC_NAME_SPLIT_RE.sub("", name, count=1).strip(" -_.:()[]") or None


def split_disc(name: str) -> tuple[str, int | None]:
    """An album name with a disc at its end: "Album CD02" -> ("Album", 2); others unchanged."""
    m = _DISC_SUFFIX_RE.match(name)
    if m and m.group(1).strip(" -_.:,"):
        return m.group(1).strip(" -_.:,"), int(m.group(2))
    return name, None


def album_dir_of(rel_dir: str) -> str:
    p = PurePosixPath(rel_dir)
    if rel_dir and is_disc_dir(p.name) is not None:
        return str(p.parent) if str(p.parent) != "." else ""
    return rel_dir


def split_year(name: str) -> tuple[str, int | None]:
    m = _YEAR_SUFFIX_RE.match(name)
    if m and m.group(1).strip():
        return m.group(1).strip(), int(m.group(2))
    m = _YEAR_PREFIX_RE.match(name)
    if m:
        return m.group(2).strip(), int(m.group(1))
    return name, None


def from_path(rel_path: str) -> PathInfo:
    p = PurePosixPath(rel_path)
    stem = p.stem.replace("_", " ").strip() or p.name
    title, track_no, disc_no = stem, None, None
    m = _TRACK_PREFIX_RE.match(stem)
    if m:
        if m.group(1):
            disc_no, track_no = int(m.group(1)), int(m.group(2))
        else:
            track_no = int(m.group(3))
        title = m.group(4).strip() or stem

    dirs = list(p.parent.parts) if str(p.parent) != "." else []
    if dirs and (d := is_disc_dir(dirs[-1])) is not None:
        disc_no = disc_no or d
        dirs = dirs[:-1]
    album = album_year = artist = None
    if dirs:
        album, d = split_disc(dirs[-1])
        disc_no = disc_no or d
        album, album_year = split_year(album)
    if len(dirs) >= 2:
        artist = dirs[-2]
    return PathInfo(
        title=title,
        track_no=track_no,
        disc_no=disc_no,
        album=album,
        album_year=album_year,
        artist=artist,
        album_dir="/".join(dirs),
    )
