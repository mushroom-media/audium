from typing import Literal

from pydantic import BaseModel, Field


class TrackOut(BaseModel):
    id: int
    title: str
    artist: str
    artist_id: int
    album: str
    album_id: int
    track_no: int | None
    disc_no: int | None
    year: int | None
    duration_ms: int
    codec: str | None
    bitrate: int | None
    cover: str | None = Field(description="Cover hash, see GET /covers/{hash}/{size}")


class ArtistRef(BaseModel):
    id: int
    name: str


class ReplayGain(BaseModel):
    track_gain: float | None
    track_peak: float | None
    album_gain: float | None
    album_peak: float | None


class TrackDetail(TrackOut):
    artists: list[ArtistRef]
    path: str = Field(description="Path relative to the library folder")
    root_id: int
    size: int
    container: str | None
    sample_rate: int | None
    bit_depth: int | None
    channels: int | None
    date: str | None
    genre: str | None
    mb_recording_id: str | None
    mb_track_id: str | None
    replaygain: ReplayGain
    tag_status: Literal["ok", "partial", "fallback", "error"]
    added_at: int


class AlbumOut(BaseModel):
    id: int
    title: str
    artist: str
    artist_id: int
    year: int | None
    track_count: int
    duration_ms: int
    compilation: bool
    added_at: int
    cover: str | None


class AlbumDetail(AlbumOut):
    tracks: list[TrackOut]


class ArtistOut(BaseModel):
    id: int
    name: str
    album_count: int
    track_count: int
    cover: str | None


class SearchOut(BaseModel):
    tracks: list[TrackOut]
    albums: list[AlbumOut]
    artists: list[ArtistOut]


# --- admin ---------------------------------------------------------------------------------


class RootOut(BaseModel):
    id: int
    path: str
    enabled: bool
    status: Literal["new", "online", "offline"]
    status_message: str | None
    last_scan_at: int | None
    track_count: int
    exclude_count: int = 0


class RootCreate(BaseModel):
    path: str = Field(max_length=4096, description="Absolute path inside the music mount, e.g. /music/a")


class RootUpdate(BaseModel):
    enabled: bool


class ExcludeCreate(BaseModel):
    rel_path: str = Field(max_length=4096, description="Sub-folder relative to the library folder")


class ExcludeOut(BaseModel):
    id: int
    root_id: int
    rel_path: str


class BrowseFolder(BaseModel):
    name: str
    path: str
    root_id: int | None


class BrowseOut(BaseModel):
    path: str
    parent: str | None
    root_id: int | None
    folders: list[BrowseFolder]


class ScanRequest(BaseModel):
    root_ids: list[int] | None = Field(None, description="Default: all enabled folders")
    force: bool = Field(False, description="Re-read tags of unchanged files too")


class JobOut(BaseModel):
    id: int
    queue: str
    type: str
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    progress: int
    total: int
    message: str | None
    result: dict | None
    error: str | None
    attempts: int
    cancel_requested: bool
    created_at: int
    started_at: int | None
    finished_at: int | None


class LibraryStats(BaseModel):
    tracks: int
    albums: int
    artists: int
    missing_tracks: int
    duration_ms: int
    tag_status: dict[str, int]
