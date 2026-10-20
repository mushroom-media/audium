"""Tiny real audio files with real tags, for tests and the synthetic test library.

Templates are encoded once with ffmpeg (1 s sine tone); copies get their tags via mutagen.
"""

import base64
import io
import shutil
import subprocess
from pathlib import Path

from mutagen.aiff import AIFF
from mutagen.asf import ASF, ASFByteArrayAttribute
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCMP, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from PIL import Image

# extension -> ffmpeg encoder arguments
FORMATS = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "32k"],
    "flac": ["-c:a", "flac"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "0"],
    "opus": ["-c:a", "libopus", "-b:a", "16k"],
    "m4a": ["-c:a", "aac", "-b:a", "32k"],
    "alac.m4a": ["-c:a", "alac"],
    "wma": ["-c:a", "wmav2", "-b:a", "32k"],
    "wav": ["-c:a", "pcm_s16le"],
    "aiff": ["-c:a", "pcm_s16be"],
}


def make_templates(target: Path, formats=FORMATS, seconds: float = 1.0) -> dict[str, Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to create audio templates")
    target.mkdir(parents=True, exist_ok=True)
    out = {}
    for fmt in formats:
        ext = fmt.rsplit(".", 1)[-1]
        path = target / f"template_{fmt.replace('.', '_')}.{ext}"
        if not path.exists():
            subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=440:duration={seconds}:sample_rate=22050",
                    "-ac",
                    "1",
                    *FORMATS[fmt],
                    "-map_metadata",
                    "-1",
                    str(path),
                ],
                check=True,
            )
        out[fmt] = path
    return out


def make_cover(color: tuple[int, int, int], size: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, "JPEG", quality=70)
    return buf.getvalue()


def write_file(template: Path, dest: Path, fmt: str, tags: dict | None, picture: bytes | None = None) -> None:
    """Copy `template` to `dest` and write `tags` (title, artist, album, albumartist, track,
    disc, date, genre, compilation, mb_release_id). tags=None leaves the file untagged."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, dest)
    if tags is None:
        return
    writer = _WRITERS[fmt.rsplit(".", 1)[-1]]
    writer(dest, {k: str(v) for k, v in tags.items() if v not in (None, "")}, picture)


def _id3_frames(tags: ID3, t: dict, picture: bytes | None) -> None:
    simple = {
        "title": TIT2,
        "artist": TPE1,
        "albumartist": TPE2,
        "album": TALB,
        "track": TRCK,
        "disc": TPOS,
        "date": TDRC,
        "genre": TCON,
        "compilation": TCMP,
    }
    for key, frame in simple.items():
        if key in t:
            tags.add(frame(encoding=3, text=[t[key]]))
    if "mb_release_id" in t:
        tags.add(TXXX(encoding=3, desc="MusicBrainz Album Id", text=[t["mb_release_id"]]))
    if picture:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=picture))


def _write_mp3(path: Path, t: dict, picture):
    tags = ID3()
    _id3_frames(tags, t, picture)
    tags.save(path)


def _write_riff(cls):
    def write(path: Path, t: dict, picture):
        f = cls(path)
        if f.tags is None:
            f.add_tags()
        _id3_frames(f.tags, t, picture)
        f.save()

    return write


_VORBIS_KEYS = {
    "title": "TITLE",
    "artist": "ARTIST",
    "albumartist": "ALBUMARTIST",
    "album": "ALBUM",
    "track": "TRACKNUMBER",
    "disc": "DISCNUMBER",
    "date": "DATE",
    "genre": "GENRE",
    "compilation": "COMPILATION",
    "mb_release_id": "MUSICBRAINZ_ALBUMID",
}


def _picture(picture: bytes) -> Picture:
    p = Picture()
    p.type = 3
    p.mime = "image/jpeg"
    p.data = picture
    return p


def _write_flac(path: Path, t: dict, picture):
    f = FLAC(path)
    for key, value in t.items():
        f[_VORBIS_KEYS[key]] = value
    if picture:
        f.add_picture(_picture(picture))
    f.save()


def _write_ogg(cls):
    def write(path: Path, t: dict, picture):
        f = cls(path)
        for key, value in t.items():
            f[_VORBIS_KEYS[key]] = value
        if picture:
            f["METADATA_BLOCK_PICTURE"] = base64.b64encode(_picture(picture).write()).decode()
        f.save()

    return write


def _write_mp4(path: Path, t: dict, picture):
    f = MP4(path)
    keys = {
        "title": "©nam",
        "artist": "©ART",
        "albumartist": "aART",
        "album": "©alb",
        "date": "©day",
        "genre": "©gen",
    }
    for key, atom in keys.items():
        if key in t:
            f[atom] = [t[key]]
    if "track" in t:
        f["trkn"] = [(int(t["track"]), 0)]
    if "disc" in t:
        f["disk"] = [(int(t["disc"]), 0)]
    if t.get("compilation") == "1":
        f["cpil"] = True
    if "mb_release_id" in t:
        f["----:com.apple.iTunes:MusicBrainz Album Id"] = [t["mb_release_id"].encode()]
    if picture:
        f["covr"] = [MP4Cover(picture, imageformat=MP4Cover.FORMAT_JPEG)]
    f.save()


def _write_wma(path: Path, t: dict, picture):
    f = ASF(path)
    keys = {
        "title": "Title",
        "artist": "Author",
        "albumartist": "WM/AlbumArtist",
        "album": "WM/AlbumTitle",
        "track": "WM/TrackNumber",
        "disc": "WM/PartOfSet",
        "date": "WM/Year",
        "genre": "WM/Genre",
        "compilation": "WM/IsCompilation",
        "mb_release_id": "MusicBrainz/Album Id",
    }
    for key, value in t.items():
        f[keys[key]] = [value]
    if picture:
        mime = "image/jpeg".encode("utf-16-le") + b"\x00\x00"
        desc = b"\x00\x00"
        blob = bytes([3]) + len(picture).to_bytes(4, "little") + mime + desc + picture
        f["WM/Picture"] = [ASFByteArrayAttribute(blob)]
    f.save()


_WRITERS = {
    "mp3": _write_mp3,
    "flac": _write_flac,
    "ogg": _write_ogg(OggVorbis),
    "opus": _write_ogg(OggOpus),
    "m4a": _write_mp4,
    "wma": _write_wma,
    "wav": _write_riff(WAVE),
    "aiff": _write_riff(AIFF),
}
