"""Locating the audio file of a track, safely."""

import os
from dataclasses import dataclass

from sqlalchemy import Connection, select

from audium.db.schema import library_roots, tracks
from audium.errors import NotFound

# container -> Content-Type for direct streaming
_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "mp4": "audio/mp4",
    "wav": "audio/wav",
    "aiff": "audio/aiff",
    "asf": "audio/x-ms-wma",
    "ape": "audio/x-ape",
    "wv": "audio/x-wavpack",
    "aac": "audio/aac",
    "webm": "audio/webm",
    "matroska": "audio/x-matroska",
}


def content_type(container: str | None) -> str:
    return _CONTENT_TYPES.get(container or "", "application/octet-stream")


@dataclass(frozen=True)
class TrackFile:
    path: str
    codec: str | None
    container: str | None
    duration_ms: int
    content_type: str


def track_file(conn: Connection, track_id: int) -> TrackFile:
    row = conn.execute(
        select(tracks.c.rel_path, tracks.c.codec, tracks.c.container, tracks.c.duration_ms, library_roots.c.path)
        .join(library_roots, library_roots.c.id == tracks.c.root_id)
        .where(
            tracks.c.id == track_id,
            tracks.c.missing_since.is_(None),
            library_roots.c.enabled.is_(True),
        )
    ).first()
    if row is None:
        raise NotFound("track not found")
    root = os.path.realpath(row.path)
    path = os.path.realpath(os.path.join(root, row.rel_path))
    # The database is trusted, but a path must never leave its library folder.
    if os.path.commonpath([root, path]) != root or not os.path.isfile(path):
        raise NotFound("file not available")
    return TrackFile(
        path=path,
        codec=row.codec,
        container=row.container,
        duration_ms=row.duration_ms,
        content_type=content_type(row.container),
    )
