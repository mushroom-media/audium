"""Binary endpoints: stream, download, getCoverArt. On errors they answer with the usual
envelope (as the spec says); on success with the file or the transcoded audio."""

import os
from collections.abc import AsyncIterator

from fastapi.responses import FileResponse, StreamingResponse

from audium.api.subsonic import ids
from audium.api.subsonic.envelope import GENERIC, NOT_FOUND, SubsonicError
from audium.api.subsonic.mapping import DIRECT_CODECS
from audium.api.subsonic.routing import Call, endpoint
from audium.errors import NotFound
from audium.media.transcode import MAX_KBPS, MIN_KBPS, TARGETS
from audium.scanner.covers import SIZES, CoverStore
from audium.services import auto as auto_service
from audium.services import catalog, streaming
from audium.services import playlists as playlist_service

# Requested format -> transcoding target. Unknown formats (e.g. "flac") get MP3, which every
# app can play, unless the file already is in that format.
_TARGET_OF = {"mp3": "mp3", "opus": "opus", "ogg": "opus", "oga": "opus", "aac": "aac", "m4a": "aac", "adts": "aac"}
# Source codec -> the target it already is (no transcoding needed for that format).
_SAME_AS = {"mp3": "mp3", "opus": "opus", "aac": "aac"}
_DEFAULT_TARGET = "mp3"
_IMMUTABLE = "private, max-age=31536000, immutable"
_DAY = "private, max-age=86400"


@endpoint("stream")
def stream(call: Call):
    track_id = ids.parse_one(call.require("id"), ids.TRACK)
    requested = (call.get("format") or "").strip().lower()
    max_kbps = call.int("maxBitRate", 0, 0) or 0
    offset_s = call.int("timeOffset", 0, 0, 86_400) or 0
    with call.db.read() as conn:
        rows = catalog.songs(conn, [track_id])
        tf = _file(conn, track_id) if rows else None
    if not rows or tf is None:
        raise SubsonicError(NOT_FOUND, "song not found")
    row = rows[0]
    src_kbps = _source_kbps(row)

    if requested == "raw" or (offset_s == 0 and _direct_ok(row.codec, requested, row.container, src_kbps, max_kbps)):
        return FileResponse(tf.path, media_type=tf.content_type, headers={"Cache-Control": "private, max-age=0"})

    transcoder = call.state.transcoder
    if transcoder.busy():
        raise SubsonicError(GENERIC, "too many transcodes running, try again shortly")
    target = TARGETS[_TARGET_OF.get(requested, _DEFAULT_TARGET)]
    kbps = min(max_kbps, target.default_kbps) if max_kbps else target.default_kbps
    kbps = max(MIN_KBPS, min(MAX_KBPS, kbps))
    remaining_s = max(0.0, tf.duration_ms / 1000 - offset_s)
    headers = {"Cache-Control": "no-store", "X-Content-Duration": f"{remaining_s:.3f}"}
    body = transcoder.stream(tf.path, target, kbps, offset_s)
    if call.bool("estimateContentLength"):
        # Some (iOS) apps need a length for their progress bar. The real size differs a little,
        # so the stream is cut or padded to exactly the announced length.
        length = int(kbps * 1000 / 8 * remaining_s)
        headers["Content-Length"] = str(length)
        body = _exact_length(body, length)
    return StreamingResponse(body, media_type=target.media_type, headers=headers)


def _file(conn, track_id: int):
    try:
        return streaming.track_file(conn, track_id)
    except NotFound:
        return None


def _source_kbps(row) -> int | None:
    if row.bitrate:
        return round(row.bitrate / 1000)
    if row.size and row.duration_ms:
        return round(row.size * 8 / row.duration_ms)  # bytes per ms -> kbit/s
    return None


def _direct_ok(codec: str | None, requested: str, container: str | None, src_kbps: int | None, max_kbps: int) -> bool:
    if codec not in DIRECT_CODECS:
        return False
    # A format audium can produce, other than the file's own: transcode. Formats it cannot
    # produce ("flac" for an MP3) are no reason to transcode.
    if requested in _TARGET_OF and requested not in (codec, container) and _TARGET_OF[requested] != _SAME_AS.get(codec):
        return False
    return not max_kbps or (src_kbps is not None and src_kbps <= max_kbps)


async def _exact_length(body, length: int) -> AsyncIterator[bytes]:
    sent = 0
    try:
        async for chunk in body:
            if sent >= length:
                break
            chunk = chunk[: length - sent]
            sent += len(chunk)
            yield chunk
    finally:
        await body.aclose()  # stops ffmpeg when the output was cut short
    while sent < length:  # decoders skip trailing zero bytes
        pad = min(64 * 1024, length - sent)
        sent += pad
        yield bytes(pad)


@endpoint("download")
def download(call: Call):
    kind, item_id = ids.parse(call.require("id"), ids.TRACK, ids.ALBUM, ids.PLAYLIST, ids.ARTIST)
    if kind != ids.TRACK:
        raise SubsonicError(GENERIC, "only single songs can be downloaded")
    with call.db.read() as conn:
        tf = _file(conn, item_id)
    if tf is None:
        raise SubsonicError(NOT_FOUND, "song not found")
    return FileResponse(tf.path, media_type=tf.content_type, filename=os.path.basename(tf.path))


@endpoint("getCoverArt")
def get_cover_art(call: Call):
    raw_id = call.require("id")
    kind, value = ids.parse(raw_id, ids.COVER, ids.ALBUM, ids.TRACK, ids.ARTIST, ids.PLAYLIST, ids.AUTO)
    with call.db.read() as conn:
        digest = _cover_hash(call, conn, kind, value)
    if not digest:
        raise SubsonicError(NOT_FOUND, "no cover")
    requested = call.int("size", 0, 0) or 0
    size = next((s for s in SIZES if s >= requested), SIZES[-1]) if requested else SIZES[-1]
    store = CoverStore(call.settings.covers_dir)
    webp = store.path(digest, size)
    if not webp.is_file():
        raise SubsonicError(NOT_FOUND, "no cover")
    headers = {"Cache-Control": _IMMUTABLE if kind == ids.COVER else _DAY, "Vary": "Accept"}
    if "image/webp" in call.request.headers.get("accept", "").lower():
        return FileResponse(webp, media_type="image/webp", headers={**headers, "ETag": f'"{digest}-{size}-w"'})
    jpeg = store.jpeg(digest, size)
    if jpeg is None:
        raise SubsonicError(NOT_FOUND, "no cover")
    return FileResponse(jpeg, media_type="image/jpeg", headers={**headers, "ETag": f'"{digest}-{size}-j"'})


def _cover_hash(call: Call, conn, kind: str, value) -> str | None:
    if kind == ids.COVER:
        return value
    if kind == ids.PLAYLIST:
        return playlist_service.get_playlist(conn, call.user, value)["cover"]  # checks view access
    if kind == ids.AUTO:
        return auto_service.get_auto(conn, call.user, value)["cover"]
    return catalog.cover_of(conn, {ids.TRACK: "track", ids.ALBUM: "album", ids.ARTIST: "artist"}[kind], value)
