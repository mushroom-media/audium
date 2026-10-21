from typing import Literal

from pydantic import BaseModel, Field

from audium.api.library_models import TrackOut

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
    cover: str | None
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


class FavoriteIds(BaseModel):
    type: Literal["track", "album", "artist"]
    ids: list[int]


class HistoryIn(BaseModel):
    track_id: int
    played_ms: int = Field(ge=0, le=86_400_000)


class HistoryEntry(BaseModel):
    played_at: int
    track: TrackOut
