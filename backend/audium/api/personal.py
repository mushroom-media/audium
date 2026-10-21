from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from audium.api.deps import current_user, get_db
from audium.api.library_models import AlbumOut
from audium.api.models import Ok, Page
from audium.api.playlist_models import FavoriteIds, HistoryEntry, HistoryIn, UserRef
from audium.db.engine import Database
from audium.db.schema import users
from audium.services import personal
from audium.services.users import User

router = APIRouter(tags=["me"])

ItemType = Literal["track", "album", "artist"]


@router.put("/favorites/{item_type}/{item_id}", response_model=Ok, summary="Add a favorite")
def add_favorite(item_type: ItemType, item_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        personal.set_favorite(conn, user.id, item_type, item_id, True)
    return Ok()


@router.delete("/favorites/{item_type}/{item_id}", response_model=Ok, summary="Remove a favorite")
def remove_favorite(
    item_type: ItemType, item_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)
):
    with db.write() as conn:
        personal.set_favorite(conn, user.id, item_type, item_id, False)
    return Ok()


@router.get("/favorites/{item_type}/ids", response_model=FavoriteIds, summary="All your favorite ids of a type")
def favorite_ids(item_type: ItemType, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return {"type": item_type, "ids": personal.favorite_ids(conn, user.id, item_type)}


@router.get("/favorites/{item_type}", response_model=Page[dict], summary="Your favorites, newest first")
def list_favorites(
    item_type: ItemType,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        items, total = personal.list_favorites(conn, user.id, item_type, limit, offset)
    return {"items": items, "total": total, "next_cursor": None}


@router.post("/history", response_model=Ok, summary="Report a played track")
def record_play(body: HistoryIn, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        personal.record_play(conn, user.id, body.track_id, body.played_ms)
    return Ok()


@router.get("/history", response_model=list[HistoryEntry], summary="Your listening history, newest first")
def history(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return personal.list_history(conn, user.id, limit, offset)


@router.get("/history/albums", response_model=list[AlbumOut], summary="Recently played albums")
def recent_albums(
    limit: int = Query(12, ge=1, le=50), user: User = Depends(current_user), db: Database = Depends(get_db)
):
    with db.read() as conn:
        return personal.recent_albums(conn, user.id, limit)


@router.get("/users", response_model=list[UserRef], summary="Active users (to share playlists with)")
def directory(user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        rows = conn.execute(
            select(users.c.id, users.c.username, users.c.display_name)
            .where(users.c.status == "active", users.c.id != user.id)
            .order_by(users.c.username)
            .limit(1000)
        ).all()
    return [UserRef(**r._mapping) for r in rows]
