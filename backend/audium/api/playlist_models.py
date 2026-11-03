from typing import Literal

from pydantic import BaseModel, Field

from audium.api.library_models import AlbumOut, ArtistOut, TrackOut
from audium.api.models import Ok
from audium.services.personal import CONTEXT_PATTERN

Visibility = Literal["private", "users"]
ShareRole = Literal["viewer", "editor"]


class UserRef(BaseModel):
    id: int
    username: str
    display_name: str


class PlaylistOut(BaseModel):
    id: int
    name: str
    description: str | None
    visibility: Visibility = Field(description="users = visible to everybody on this server")
    kind: str = Field(description="manual | smart | frozen_auto")
    rule: dict | None = Field(None, description="Rule of a smart playlist")
    owner: UserRef
    role: Literal["owner", "editor", "viewer"] = Field(description="Your role on this playlist")
    version: int = Field(description="Increases with every change; send as If-Match to detect conflicts")
    item_count: int
    duration_ms: int
    cover: str | None = Field(description="Cover hash: the uploaded image, else the first track's cover")
    cover_preset: int | None = Field(None, description="Built-in cover design (1-25), drawn by the client")
    cover_source: Literal["auto", "preset", "upload"] = "auto"
    created_at: int
    updated_at: int


class PlaylistCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = Field(None, max_length=2000)
    visibility: Visibility = "private"
    track_ids: list[int] = Field(default_factory=list, max_length=5000)
    rule: dict | None = Field(None, description="Makes a smart playlist; see GET /rules/fields")


class PlaylistUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    visibility: Visibility | None = None
    rule: dict | None = None


class CoverChoice(BaseModel):
    preset: int | None = Field(None, ge=1, le=25, description="Built-in design; null = the first track's cover")


class PlaylistItemOut(BaseModel):
    item_id: int
    added_by: int | None
    added_at: int
    available: bool = Field(description="False while the file is missing from the library")
    track: TrackOut


class PlaylistItemsPage(BaseModel):
    items: list[PlaylistItemOut]
    total: int
    version: int


class ItemsAdd(BaseModel):
    track_ids: list[int] = Field(min_length=1, max_length=5000)
    position: Literal["end", "start", "after"] = "end"
    after_item_id: int | None = Field(None, description="Required with position=after")


class ItemsRemove(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=5000)


class ItemMove(BaseModel):
    after_item_id: int | None = Field(None, description="Move behind this item; null = to the start")


class ItemsChanged(BaseModel):
    version: int
    item_ids: list[int] = Field(default_factory=list, description="Ids of newly added items")


class ShareOut(BaseModel):
    user: UserRef
    role: ShareRole


class ShareSet(BaseModel):
    role: ShareRole


class TopTrack(BaseModel):
    track: TrackOut
    plays: int
    listening_ms: int = Field(description="Time the plays really sounded (see StatsOut)")


class TopAlbum(BaseModel):
    album: AlbumOut
    plays: int
    listening_ms: int = Field(description="Time the plays really sounded (see StatsOut)")


class TopArtist(BaseModel):
    artist: ArtistOut
    plays: int
    listening_ms: int = Field(description="Time the plays really sounded (see StatsOut); artists are ranked by it")


class StatsOut(BaseModel):
    since: int | None = Field(description="Start of the period (ms); null = the whole history")
    plays: int
    listening_ms: int = Field(
        description="Time the plays really sounded; plays without a measurement (older ones, Subsonic apps) "
        "count with the track's length"
    )
    tracks: list[TopTrack]
    albums: list[TopAlbum]
    artists: list[TopArtist]


class FavoriteIds(BaseModel):
    type: Literal["track", "album", "artist"]
    ids: list[int]


class HistoryIn(BaseModel):
    track_id: int
    played_ms: int = Field(ge=0, le=86_400_000, description="Position in the track when the play was reported")
    listened_ms: int | None = Field(
        None, ge=0, le=86_400_000, description="Time it really sounded so far (no pauses, buffering or skipped parts)"
    )
    context: str | None = Field(
        None,
        pattern=CONTEXT_PATTERN,
        description='Played from: "album:ID", "playlist:ID", "auto:ID", "favorites" or "radio:track|album|artist:ID"',
    )


class HistoryRecorded(Ok):
    id: int = Field(description="The play, for reporting the final listened time later")


class ListenedIn(BaseModel):
    listened_ms: int = Field(ge=0, le=86_400_000, description="Time the play really sounded in all")


class RecentOut(BaseModel):
    type: Literal["album", "playlist", "auto", "favorites", "radio"]
    id: int | None
    radio_of: Literal["track", "album", "artist"] | None = Field(description="Radios: what the station started from")
    name: str
    subtitle: str | None
    cover: str | None
    cover_preset: int | None


class HistoryEntry(BaseModel):
    played_at: int
    client: str | None = Field(None, description="App that played it (Subsonic clients); null = web UI")
    track: TrackOut
