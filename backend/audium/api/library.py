import re
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from audium.api.deps import current_user, get_db, get_settings
from audium.api.library_models import AlbumDetail, AlbumOut, ArtistOut, SearchOut, TrackDetail, TrackOut
from audium.api.models import Page
from audium.config import Settings
from audium.db.engine import Database
from audium.errors import BadRequest, NotFound
from audium.scanner.covers import SIZES, CoverStore
from audium.services import library as lib
from audium.services.users import User

router = APIRouter(tags=["library"])

Order = Literal["asc", "desc"]
_HASH_RE = re.compile(r"^[0-9a-f]{32}$")
_COVER_CACHE = "private, max-age=31536000, immutable"

LIMIT = Query(100, ge=1, le=500)
OFFSET = Query(0, ge=0, le=10_000_000, description="Jump to a position (ignored when cursor is set)")
CURSOR = Query(None, max_length=2048)


@router.get("/tracks", response_model=Page[TrackOut])
def list_tracks(
    request: Request,
    sort: Literal["title", "added", "year"] = "title",
    order: Order | None = None,
    cursor: str | None = CURSOR,
    offset: int = OFFSET,
    limit: int = LIMIT,
    artist_id: int | None = None,
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        items, next_cursor, total = lib.list_tracks(
            conn,
            request.app.state.counts,
            sort=sort,
            order=order,
            cursor=cursor,
            offset=offset,
            limit=limit,
            artist_id=artist_id,
        )
    return {"items": items, "next_cursor": next_cursor, "total": total}


@router.get("/tracks/{track_id}", response_model=TrackDetail)
def get_track(track_id: int, _user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return lib.get_track(conn, track_id)


@router.get("/albums", response_model=Page[AlbumOut])
def list_albums(
    request: Request,
    sort: Literal["title", "artist", "year", "added"] = "title",
    order: Order | None = None,
    cursor: str | None = CURSOR,
    offset: int = OFFSET,
    limit: int = LIMIT,
    artist_id: int | None = None,
    year_from: int | None = Query(None, ge=0, le=3000),
    year_to: int | None = Query(None, ge=0, le=3000),
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        items, next_cursor, total = lib.list_albums(
            conn,
            request.app.state.counts,
            sort=sort,
            order=order,
            cursor=cursor,
            offset=offset,
            limit=limit,
            artist_id=artist_id,
            year_from=year_from,
            year_to=year_to,
        )
    return {"items": items, "next_cursor": next_cursor, "total": total}


@router.get("/albums/{album_id}", response_model=AlbumDetail)
def get_album(album_id: int, _user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return lib.get_album(conn, album_id)


@router.get("/artists", response_model=Page[ArtistOut])
def list_artists(
    request: Request,
    sort: Literal["name"] = "name",
    order: Order | None = None,
    cursor: str | None = CURSOR,
    offset: int = OFFSET,
    limit: int = LIMIT,
    role: Literal["album", "all"] = Query("album", description="album: album artists only"),
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        items, next_cursor, total = lib.list_artists(
            conn,
            request.app.state.counts,
            sort=sort,
            order=order,
            cursor=cursor,
            offset=offset,
            limit=limit,
            role=role,
        )
    return {"items": items, "next_cursor": next_cursor, "total": total}


@router.get("/artists/{artist_id}", response_model=ArtistOut)
def get_artist(artist_id: int, _user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return lib.get_artist(conn, artist_id)


@router.get("/search", response_model=SearchOut, summary="Prefix search over titles, artists and albums")
def search(
    q: str = Query(..., max_length=200),
    types: str = Query("track,album,artist", description="Comma-separated: track, album, artist"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    wanted = [t.strip() for t in types.split(",") if t.strip()]
    if not wanted or any(t not in lib.SEARCH_TYPES for t in wanted):
        raise BadRequest("types must be a comma-separated subset of track, album, artist")
    with db.read() as conn:
        return lib.search_all(conn, q, wanted, limit, offset)


@router.get(
    "/covers/{digest}/{size}",
    response_class=FileResponse,
    summary="Cover thumbnail (WebP). The URL never changes for an image, so it is cached forever.",
)
def cover(
    digest: str,
    size: int,
    _user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    if not _HASH_RE.match(digest) or size not in SIZES:
        raise NotFound("cover not found")
    path = CoverStore(settings.covers_dir).path(digest, size)
    if not path.is_file():
        raise NotFound("cover not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": _COVER_CACHE, "ETag": f'"{digest}-{size}"'},
    )
