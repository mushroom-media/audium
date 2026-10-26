import re
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from audium.api.deps import current_user, get_db, get_settings, media_user
from audium.api.library_models import (
    AlbumDetail,
    AlbumOut,
    ArtistOut,
    LetterOut,
    SearchOut,
    TrackDetail,
    TrackOut,
)
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
MAX_BY_IDS = 200
FILTER = Query(None, max_length=200, description="Keep only full-text matches (prefix, like /search), in list order")


@router.get("/tracks", response_model=Page[TrackOut])
def list_tracks(
    request: Request,
    sort: Literal["title", "added", "year"] = "title",
    order: Order | None = None,
    cursor: str | None = CURSOR,
    offset: int = OFFSET,
    limit: int = LIMIT,
    artist_id: int | None = None,
    q: str | None = FILTER,
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
            q=q,
        )
    return {"items": items, "next_cursor": next_cursor, "total": total}


@router.get("/tracks/ids", response_model=list[int], summary="All ids of a track list, in list order")
def list_track_ids(
    sort: Literal["title", "added", "year"] = "title",
    order: Order | None = None,
    artist_id: int | None = None,
    q: str | None = FILTER,
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return lib.track_ids(conn, sort=sort, order=order, artist_id=artist_id, q=q)


@router.get("/tracks/by-ids", response_model=list[TrackOut], summary="Tracks by id, in the given order")
def tracks_by_ids(
    ids: list[int] = Query([], max_length=MAX_BY_IDS),
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return lib.tracks_by_ids(conn, ids)


@router.get("/tracks/letters", response_model=list[LetterOut], summary="A-Z index of the tracks sorted by title")
def track_letters(q: str | None = FILTER, _user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return lib.track_letters(conn, q)


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
    artist_id: int | None = Query(None, description="Albums whose album artist this is"),
    appears_on: int | None = Query(None, description="Albums of other artists with tracks by this artist"),
    year_from: int | None = Query(None, ge=0, le=3000),
    year_to: int | None = Query(None, ge=0, le=3000),
    q: str | None = FILTER,
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
            appears_on=appears_on,
            year_from=year_from,
            year_to=year_to,
            q=q,
        )
    return {"items": items, "next_cursor": next_cursor, "total": total}


@router.get("/albums/letters", response_model=list[LetterOut], summary="A-Z index of the albums (ascending sort)")
def album_letters(
    sort: Literal["title", "artist"] = "title",
    q: str | None = FILTER,
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return lib.album_letters(conn, sort, q)


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
    q: str | None = FILTER,
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
            q=q,
        )
    return {"items": items, "next_cursor": next_cursor, "total": total}


@router.get("/artists/letters", response_model=list[LetterOut], summary="A-Z index of the artists")
def artist_letters(
    role: Literal["album", "all"] = Query("album", description="album: album artists only"),
    q: str | None = FILTER,
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return lib.artist_letters(conn, role, q)


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
    _user: User = Depends(media_user),
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
