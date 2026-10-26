from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.concurrency import run_in_threadpool

from audium.api.deps import current_user, get_db, get_settings
from audium.api.models import Ok
from audium.api.playlist_models import (
    CoverChoice,
    ItemMove,
    ItemsAdd,
    ItemsChanged,
    ItemsRemove,
    PlaylistCreate,
    PlaylistItemsPage,
    PlaylistOut,
    PlaylistUpdate,
    ShareOut,
    ShareSet,
)
from audium.config import Settings
from audium.db.engine import Database
from audium.errors import BadRequest
from audium.scanner.covers import CoverStore
from audium.services import playlists as svc
from audium.services.permissions import require_playlist
from audium.services.users import User

router = APIRouter(prefix="/playlists", tags=["playlists"])

MAX_COVER_BYTES = 10_000_000

IF_MATCH = Header(None, alias="If-Match", description="Expected playlist version; 409 if it changed")


def _version(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    try:
        return int(if_match.strip().strip('"').removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise BadRequest("If-Match must be a playlist version number") from exc


def _publish(request: Request, *events) -> None:
    request.app.state.bus.publish(*events)


@router.get("", response_model=list[PlaylistOut], summary="Playlists you can see")
def list_playlists(
    scope: Literal["all", "mine", "shared", "public"] = "all",
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return svc.list_playlists(conn, user, scope, limit, offset)


@router.post("", response_model=PlaylistOut, status_code=201)
def create_playlist(
    body: PlaylistCreate, request: Request, user: User = Depends(current_user), db: Database = Depends(get_db)
):
    with db.write() as conn:
        out, event = svc.create_playlist(
            conn, user, body.name, body.description, body.visibility, body.track_ids, body.rule
        )
    _publish(request, event)
    return out


@router.get("/{playlist_id}", response_model=PlaylistOut)
def get_playlist(playlist_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return svc.get_playlist(conn, user, playlist_id)


@router.patch("/{playlist_id}", response_model=PlaylistOut, summary="Rename, describe, change visibility (owner)")
def update_playlist(
    playlist_id: int,
    body: PlaylistUpdate,
    request: Request,
    if_match: str | None = IF_MATCH,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.write() as conn:
        out, event = svc.update_playlist(
            conn,
            user,
            playlist_id,
            name=body.name,
            description=body.description,
            visibility=body.visibility,
            rule=body.rule,
            if_version=_version(if_match),
        )
    _publish(request, event)
    return out


@router.put("/{playlist_id}/cover", response_model=PlaylistOut, summary="Pick a built-in cover or reset it (owner)")
def choose_cover(
    playlist_id: int,
    body: CoverChoice,
    request: Request,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.write() as conn:
        out, event = svc.set_cover(conn, user, playlist_id, preset=body.preset)
    _publish(request, event)
    return out


@router.post(
    "/{playlist_id}/cover",
    response_model=PlaylistOut,
    summary="Upload a cover image (owner). The body is the image itself (JPEG, PNG, WebP, ...).",
)
async def upload_cover(
    playlist_id: int,
    request: Request,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if int(request.headers.get("content-length") or 0) > MAX_COVER_BYTES:
        raise BadRequest(f"the image must be smaller than {MAX_COVER_BYTES // 1_000_000} MB")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_COVER_BYTES:
            raise BadRequest(f"the image must be smaller than {MAX_COVER_BYTES // 1_000_000} MB")
    return await run_in_threadpool(_store_upload, playlist_id, bytes(data), request, user, db, settings)


def _store_upload(playlist_id: int, data: bytes, request: Request, user: User, db: Database, settings: Settings):
    with db.read() as conn:
        require_playlist(conn, user, playlist_id, "manage")  # before spending time on the image
    rendered = CoverStore(settings.covers_dir).ingest(data)
    if rendered is None:
        raise BadRequest("not a readable image")
    with db.write() as conn:
        out, event = svc.set_cover(conn, user, playlist_id, upload=rendered)
    _publish(request, event)
    return out


@router.delete("/{playlist_id}", response_model=Ok, summary="Delete (owner)")
def delete_playlist(
    playlist_id: int, request: Request, user: User = Depends(current_user), db: Database = Depends(get_db)
):
    with db.write() as conn:
        event = svc.delete_playlist(conn, user, playlist_id)
    _publish(request, event)
    return Ok()


@router.get("/{playlist_id}/items", response_model=PlaylistItemsPage)
def list_items(
    playlist_id: int,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        items, total = svc.list_items(conn, user, playlist_id, limit, offset)
        version = svc.get_playlist(conn, user, playlist_id)["version"]
    return {"items": items, "total": total, "version": version}


@router.post("/{playlist_id}/items", response_model=ItemsChanged, summary="Add tracks (owner, editor)")
def add_items(
    playlist_id: int,
    body: ItemsAdd,
    request: Request,
    if_match: str | None = IF_MATCH,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    if body.position == "after" and body.after_item_id is None:
        raise BadRequest("after_item_id is required with position=after")
    with db.write() as conn:
        item_ids, version, event = svc.add_items(
            conn,
            user,
            playlist_id,
            body.track_ids,
            after_item_id=body.after_item_id if body.position == "after" else None,
            at_end=body.position == "end",
            if_version=_version(if_match),
        )
    _publish(request, event)
    return {"version": version, "item_ids": item_ids}


@router.post("/{playlist_id}/items/remove", response_model=ItemsChanged, summary="Remove items (owner, editor)")
def remove_items(
    playlist_id: int,
    body: ItemsRemove,
    request: Request,
    if_match: str | None = IF_MATCH,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.write() as conn:
        version, event = svc.remove_items(conn, user, playlist_id, body.item_ids, _version(if_match))
    _publish(request, event)
    return {"version": version}


@router.post("/{playlist_id}/items/{item_id}/move", response_model=ItemsChanged, summary="Reorder (owner, editor)")
def move_item(
    playlist_id: int,
    item_id: int,
    body: ItemMove,
    request: Request,
    if_match: str | None = IF_MATCH,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.write() as conn:
        version, event = svc.move_item(conn, user, playlist_id, item_id, body.after_item_id, _version(if_match))
    _publish(request, event)
    return {"version": version}


@router.get("/{playlist_id}/shares", response_model=list[ShareOut])
def list_shares(playlist_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return svc.list_shares(conn, user, playlist_id)


@router.put("/{playlist_id}/shares/{user_id}", response_model=list[ShareOut], summary="Share with a user (owner)")
def set_share(
    playlist_id: int,
    user_id: int,
    body: ShareSet,
    request: Request,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.write() as conn:
        shares, event = svc.set_share(conn, user, playlist_id, user_id, body.role)
    _publish(request, event)
    return shares


@router.delete("/{playlist_id}/shares/{user_id}", response_model=list[ShareOut], summary="Stop sharing (owner)")
def remove_share(
    playlist_id: int,
    user_id: int,
    request: Request,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.write() as conn:
        shares, event = svc.remove_share(conn, user, playlist_id, user_id)
    _publish(request, event)
    return shares


@router.post("/{playlist_id}/leave", response_model=Ok, summary="Remove a playlist shared with you from your list")
def leave(playlist_id: int, request: Request, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        event = svc.leave_share(conn, user, playlist_id)
    _publish(request, event)
    return Ok()
