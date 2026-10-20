"""Reads tags, stream info and the embedded cover of one audio file.

`read_track` never raises: broken or untagged files return whatever could be read, the scanner
fills the gaps from the path (see fallback.py). Every tag system is first mapped to the same
canonical keys (`raw`), then parsed in one place.
"""

import base64
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field

import mutagen
from mutagen._vorbis import VCommentDict
from mutagen.apev2 import APEv2
from mutagen.asf import ASF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from audium.scanner.formats import FFPROBE_CODECS, codec_for
from audium.util import clean_text

_MAX_PICTURE_BYTES = 20 * 1024 * 1024
_FRONT_COVER = 3
_FFPROBE_TIMEOUT_S = 20


@dataclass
class TrackMeta:
    title: str | None = None
    artist_display: str | None = None
    artists: list[str] = field(default_factory=list)
    album_artists: list[str] = field(default_factory=list)
    album: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    date: str | None = None
    year: int | None = None
    genres: list[str] = field(default_factory=list)
    compilation: bool = False
    mb_recording_id: str | None = None
    mb_track_id: str | None = None
    mb_release_id: str | None = None
    mb_artist_id: str | None = None
    mb_album_artist_id: str | None = None
    rg_track_gain: float | None = None
    rg_track_peak: float | None = None
    rg_album_gain: float | None = None
    rg_album_peak: float | None = None
    duration_ms: int = 0
    bitrate: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    codec: str | None = None
    container: str | None = None
    picture: bytes | None = None
    has_tags: bool = False
    error: str | None = None


# --- canonical key maps per tag system -----------------------------------------------------

_COMMON = {
    "artists": "artists",
    "musicbrainz_trackid": "mb_recording_id",
    "musicbrainz_releasetrackid": "mb_track_id",
    "musicbrainz_albumid": "mb_release_id",
    "musicbrainz_artistid": "mb_artist_id",
    "musicbrainz_albumartistid": "mb_albumartist_id",
    "replaygain_track_gain": "rg_track_gain",
    "replaygain_track_peak": "rg_track_peak",
    "replaygain_album_gain": "rg_album_gain",
    "replaygain_album_peak": "rg_album_peak",
}

_VORBIS = {
    **_COMMON,
    "title": "title",
    "artist": "artist",
    "albumartist": "albumartist",
    "album artist": "albumartist",
    "album_artist": "albumartist",
    "album": "album",
    "tracknumber": "track",
    "discnumber": "disc",
    "date": "date",
    "year": "year",
    "originaldate": "originaldate",
    "genre": "genre",
    "compilation": "compilation",
}

_APE = {
    **_COMMON,
    "title": "title",
    "artist": "artist",
    "album artist": "albumartist",
    "albumartist": "albumartist",
    "album": "album",
    "track": "track",
    "disc": "disc",
    "year": "date",
    "genre": "genre",
    "compilation": "compilation",
}

_ID3_TEXT = {
    "TIT2": "title",
    "TPE1": "artist",
    "TPE2": "albumartist",
    "TALB": "album",
    "TRCK": "track",
    "TPOS": "disc",
    "TDRC": "date",
    "TDOR": "originaldate",
    "TCMP": "compilation",
}
_ID3_TXXX = {
    "musicbrainz album id": "mb_release_id",
    "musicbrainz release track id": "mb_track_id",
    "musicbrainz artist id": "mb_artist_id",
    "musicbrainz album artist id": "mb_albumartist_id",
    "artists": "artists",
    "replaygain_track_gain": "rg_track_gain",
    "replaygain_track_peak": "rg_track_peak",
    "replaygain_album_gain": "rg_album_gain",
    "replaygain_album_peak": "rg_album_peak",
}

_MP4 = {
    "©nam": "title",
    "©art": "artist",
    "aart": "albumartist",
    "©alb": "album",
    "©day": "date",
    "©gen": "genre",
}
_MP4_FREEFORM = {
    "musicbrainz track id": "mb_recording_id",
    "musicbrainz release track id": "mb_track_id",
    "musicbrainz album id": "mb_release_id",
    "musicbrainz artist id": "mb_artist_id",
    "musicbrainz album artist id": "mb_albumartist_id",
    "artists": "artists",
    "replaygain_track_gain": "rg_track_gain",
    "replaygain_track_peak": "rg_track_peak",
    "replaygain_album_gain": "rg_album_gain",
    "replaygain_album_peak": "rg_album_peak",
}

_ASF = {
    "title": "title",
    "author": "artist",
    "wm/albumartist": "albumartist",
    "wm/albumtitle": "album",
    "wm/tracknumber": "track",
    "wm/partofset": "disc",
    "wm/year": "date",
    "wm/genre": "genre",
    "wm/iscompilation": "compilation",
    "musicbrainz/track id": "mb_recording_id",
    "musicbrainz/release track id": "mb_track_id",
    "musicbrainz/album id": "mb_release_id",
    "musicbrainz/artist id": "mb_artist_id",
    "musicbrainz/album artist id": "mb_albumartist_id",
    **{k: v for k, v in _COMMON.items() if k.startswith("replaygain")},
}

_FFPROBE = {**_VORBIS, "track": "track", "disc": "disc"}

Raw = dict[str, list[str]]
Pictures = list[tuple[int, bytes]]


def _add(raw: Raw, key: str | None, values) -> None:
    if key is None:
        return
    for v in values:
        s = str(v)
        if s:
            raw.setdefault(key, []).append(s)


def _from_vorbis(tags) -> tuple[Raw, Pictures]:
    raw: Raw = {}
    pics: Pictures = []
    for key, value in tags:
        k = key.lower()
        if k == "metadata_block_picture":
            try:
                p = Picture(base64.b64decode(value))
                pics.append((p.type, p.data))
            except Exception:
                pass
        elif k == "coverart":
            try:
                pics.append((_FRONT_COVER, base64.b64decode(value)))
            except Exception:
                pass
        else:
            _add(raw, _VORBIS.get(k), [value])
    return raw, pics


def _from_id3(tags: ID3) -> tuple[Raw, Pictures]:
    raw: Raw = {}
    for frame_id, key in _ID3_TEXT.items():
        frame = tags.get(frame_id)
        if frame is not None and getattr(frame, "text", None):
            _add(raw, key, frame.text)
    tcon = tags.get("TCON")
    if tcon is not None:
        _add(raw, "genre", tcon.genres)
    for frame in tags.getall("TXXX"):
        _add(raw, _ID3_TXXX.get(frame.desc.lower()), frame.text)
    for frame in tags.getall("UFID"):
        if frame.owner == "http://musicbrainz.org":
            _add(raw, "mb_recording_id", [frame.data.decode("ascii", "ignore")])
    pics = [(int(f.type), f.data) for f in tags.getall("APIC")]
    return raw, pics


def _from_mp4(tags) -> tuple[Raw, Pictures]:
    raw: Raw = {}
    pics: Pictures = []
    for key, values in tags.items():
        k = key.lower()
        if k in _MP4:
            _add(raw, _MP4[k], values)
        elif k in ("trkn", "disk") and values:
            num = values[0][0] if isinstance(values[0], tuple) else values[0]
            _add(raw, "track" if k == "trkn" else "disc", [num])
        elif k == "cpil":
            _add(raw, "compilation", ["1" if values else "0"])
        elif k == "covr":
            pics.extend((_FRONT_COVER, bytes(v)) for v in values)
        elif k.startswith("----:com.apple.itunes:"):
            name = k.split(":", 2)[2]
            _add(raw, _MP4_FREEFORM.get(name), [bytes(v).decode("utf-8", "replace") for v in values])
    return raw, pics


def _parse_asf_picture(data: bytes) -> tuple[int, bytes] | None:
    # WM/Picture: type (1 byte), data size (4 bytes LE), mime (UTF-16LE, NUL), description (UTF-16LE, NUL), data
    try:
        pic_type = data[0]
        size = int.from_bytes(data[1:5], "little")
        pos = 5
        for _ in range(2):  # skip mime type and description
            while data[pos : pos + 2] != b"\x00\x00":
                pos += 2
            pos += 2
        return pic_type, data[pos : pos + size]
    except Exception:
        return None


def _from_asf(tags) -> tuple[Raw, Pictures]:
    raw: Raw = {}
    pics: Pictures = []
    for key in set(tags.keys()):
        values = [v.value for v in tags[key]]
        k = key.lower()
        if k == "wm/picture":
            pics.extend(p for p in (_parse_asf_picture(bytes(v)) for v in values) if p)
        elif k == "wm/track" and "track" not in raw:
            _add(raw, "track0", values)  # 0-based legacy field
        else:
            _add(raw, _ASF.get(k), values)
    if "track" not in raw and "track0" in raw:
        try:
            raw["track"] = [str(int(raw["track0"][0]) + 1)]
        except ValueError:
            pass
    raw.pop("track0", None)
    return raw, pics


def _from_ape(tags: APEv2) -> tuple[Raw, Pictures]:
    raw: Raw = {}
    pics: Pictures = []
    for key, value in tags.items():
        k = key.lower()
        if k.startswith("cover art"):
            data = bytes(value.value)
            _, _, img = data.partition(b"\x00")
            pics.append((_FRONT_COVER if "front" in k else 0, img))
        elif getattr(value, "kind", 0) == 0:  # text
            _add(raw, _APE.get(k), str(value).split("\x00"))
    return raw, pics


def _extract(audio) -> tuple[Raw, Pictures]:
    tags = audio.tags
    raw: Raw = {}
    pics: Pictures = []
    if tags is not None:
        if isinstance(audio, MP4):
            raw, pics = _from_mp4(tags)
        elif isinstance(audio, ASF):
            raw, pics = _from_asf(tags)
        elif isinstance(tags, ID3):
            raw, pics = _from_id3(tags)
        elif isinstance(tags, APEv2):
            raw, pics = _from_ape(tags)
        elif isinstance(tags, VCommentDict):
            raw, pics = _from_vorbis(tags)
    if isinstance(audio, FLAC):
        pics.extend((p.type, p.data) for p in audio.pictures)
    return raw, pics


# --- parsing -------------------------------------------------------------------------------

_INT_RE = re.compile(r"^\s*(\d{1,4})")
_YEAR_RE = re.compile(r"(\d{4})")
_GAIN_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)")
_MULTI_SPLIT_RE = re.compile(r"\s*;\s*")


def _first(raw: Raw, key: str) -> str | None:
    for v in raw.get(key, ()):
        c = clean_text(v)
        if c:
            return c
    return None


def _many(raw: Raw, key: str) -> list[str]:
    """All values of a multi-value field. ';' also separates values; '/' and '&' do not
    (AC/DC, Simon & Garfunkel)."""
    out: list[str] = []
    for v in raw.get(key, ()):
        for part in _MULTI_SPLIT_RE.split(str(v)):
            c = clean_text(part, 256)
            if c and c not in out:
                out.append(c)
    return out


def parse_number(value: str | None) -> int | None:
    if not value:
        return None
    m = _INT_RE.match(value)
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 < n < 10000 else None


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    m = _YEAR_RE.search(value)
    if not m:
        return None
    y = int(m.group(1))
    return y if 1000 <= y <= 2100 else None


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    m = _GAIN_RE.match(value)
    return float(m.group(1)) if m else None


def _apply(raw: Raw, meta: TrackMeta) -> None:
    meta.has_tags = any(raw.get(k) for k in ("title", "artist", "album", "albumartist"))
    meta.title = _first(raw, "title")
    artist_values = [c for c in (clean_text(v) for v in raw.get("artist", ())) if c]
    meta.artist_display = ", ".join(dict.fromkeys(artist_values)) or None
    meta.artists = _many(raw, "artists") or _many(raw, "artist")
    meta.album_artists = _many(raw, "albumartist")
    meta.album = _first(raw, "album")
    meta.track_no = parse_number(_first(raw, "track"))
    meta.disc_no = parse_number(_first(raw, "disc"))
    meta.date = _first(raw, "date") or _first(raw, "year") or _first(raw, "originaldate")
    meta.year = parse_year(meta.date)
    meta.genres = _many(raw, "genre")
    meta.compilation = (_first(raw, "compilation") or "").lower() in ("1", "true", "yes")
    for key in ("mb_recording_id", "mb_track_id", "mb_release_id", "mb_artist_id"):
        setattr(meta, key, _first(raw, key))
    meta.mb_album_artist_id = _first(raw, "mb_albumartist_id")
    for key in ("rg_track_gain", "rg_track_peak", "rg_album_gain", "rg_album_peak"):
        setattr(meta, key, parse_float(_first(raw, key)))


def _best_picture(pics: Pictures) -> bytes | None:
    usable = [(t, d) for t, d in pics if d and len(d) <= _MAX_PICTURE_BYTES]
    if not usable:
        return None
    usable.sort(key=lambda p: (p[0] != _FRONT_COVER, p[0] != 0))
    return usable[0][1]


def _stream_info(audio, meta: TrackMeta) -> None:
    info = audio.info
    length = getattr(info, "length", 0) or 0
    meta.duration_ms = max(0, int(length * 1000))
    meta.bitrate = int(getattr(info, "bitrate", 0) or 0) or None
    meta.sample_rate = int(getattr(info, "sample_rate", 0) or 0) or None
    meta.channels = int(getattr(info, "channels", 0) or 0) or None
    meta.bit_depth = int(getattr(info, "bits_per_sample", 0) or 0) or None
    meta.codec, meta.container = codec_for(audio)


def _probe(path: str, meta: TrackMeta) -> None:
    """Last resort for files mutagen cannot parse (and containers it does not know, e.g. MKA)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True,
            timeout=_FFPROBE_TIMEOUT_S,
            check=False,
        )
        data = json.loads(out.stdout or b"{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if stream is None:
        return
    fmt = data.get("format", {})
    meta.error = None  # ffmpeg can read it, so it is playable after all
    duration = float(fmt.get("duration") or stream.get("duration") or 0)
    meta.duration_ms = int(duration * 1000)
    meta.codec = FFPROBE_CODECS.get(stream.get("codec_name", ""), stream.get("codec_name"))
    meta.container = (fmt.get("format_name") or "").split(",")[0] or None
    meta.sample_rate = int(stream.get("sample_rate") or 0) or None
    meta.channels = int(stream.get("channels") or 0) or None
    meta.bitrate = int(fmt.get("bit_rate") or stream.get("bit_rate") or 0) or None
    meta.bit_depth = int(stream.get("bits_per_raw_sample") or 0) or None
    raw: Raw = {}
    for source in (fmt.get("tags", {}), stream.get("tags", {})):
        for k, v in source.items():
            _add(raw, _FFPROBE.get(k.lower()), [v])
    _apply(raw, meta)


def read_track(path: str) -> TrackMeta:
    meta = TrackMeta()
    try:
        audio = mutagen.File(path)
    except Exception as exc:
        audio = None
        meta.error = f"{type(exc).__name__}: {exc}"[:300]
    if audio is None:
        _probe(path, meta)
        return meta
    try:
        _stream_info(audio, meta)
    except Exception as exc:
        meta.error = f"stream info: {type(exc).__name__}: {exc}"[:300]
    try:
        raw, pics = _extract(audio)
        _apply(raw, meta)
        meta.picture = _best_picture(pics)
    except Exception as exc:
        meta.error = f"tags: {type(exc).__name__}: {exc}"[:300]
    if meta.duration_ms == 0 and meta.codec is None:
        _probe(path, meta)
    return meta
