"""Auto-playlists, rules, similar tracks and radio."""

import numpy as np
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from audium.analysis import rules
from audium.analysis.similarity import fallback_similar, radio
from audium.analysis.tasks import analysis_stats, enqueue_analysis, enqueue_autoplaylists
from audium.api.deps import current_user, get_db, require_admin
from audium.api.library_models import TrackOut
from audium.api.models import Ok
from audium.api.playlist_models import PlaylistOut
from audium.db.engine import Database
from audium.db.pagination import fetch_ordered
from audium.db.schema import genres, library_roots, track_features, tracks
from audium.errors import NotFound
from audium.services import auto as auto_service
from audium.services.library import track_item, track_select
from audium.services.users import User

router = APIRouter(tags=["discover"])
admin = APIRouter(prefix="/admin", tags=["admin: discover"])


class GenreOut(BaseModel):
    name: str
    slug: str
    track_count: int


class AutoPlaylistOut(BaseModel):
    id: int
    key: str
    generator: str = Field(description="tag | rule | cluster | custom")
    name: str
    description: str | None
    track_count: int
    duration_ms: int
    cover: str | None
    generated_at: int | None
    rule: dict | None
    status: str | None = Field(None, description="Admins only: suggested | published | dismissed")
    access: str | None = Field(None, description="Admins only: all | restricted | admin_only")
    user_ids: list[int] | None = Field(None, description="Admins only: users with access when restricted")


class AutoItemOut(BaseModel):
    reason: str | None = Field(description='Why the track is in here, e.g. "128 BPM · hohe Energie"')
    track: TrackOut


class AutoItemsPage(BaseModel):
    items: list[AutoItemOut]
    total: int


class FreezeIn(BaseModel):
    name: str | None = Field(None, max_length=200)


class RulePreviewIn(BaseModel):
    rule: dict


class RulePreviewOut(BaseModel):
    count: int = Field(description="Matching tracks (up to the rule's limit)")
    tracks: list[TrackOut]
    needs_analysis: bool


class AutoUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    status: str | None = None
    access: str | None = None
    user_ids: list[int] | None = None
    rule: dict | None = None


class AutoCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = Field(None, max_length=2000)
    rule: dict
    access: str = "all"


class AnalysisStatus(BaseModel):
    backend: str = Field(description="essentia | essentia+ml | none | unknown")
    tracks: int
    analyzed: int
    failed: int
    pending: int


class AnalysisFailure(BaseModel):
    track_id: int
    path: str
    error: str | None


def _tracks(conn, ids: list[int]) -> list[dict]:
    return [track_item(r) for r in fetch_ordered(conn, track_select(), tracks.c.id, ids)]


@router.get("/genres", response_model=list[GenreOut], summary="Normalized genres with track counts")
def list_genres(_user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        rows = conn.execute(
            select(genres.c.name, genres.c.slug, genres.c.track_count)
            .where(genres.c.track_count > 0)
            .order_by(genres.c.track_count.desc(), genres.c.name)
            .limit(2000)
        ).all()
    return [GenreOut(**r._mapping) for r in rows]


@router.get("/rules/fields", summary="Fields, operators and values for the rule editor")
def rule_fields(_user: User = Depends(current_user)):
    return {"fields": rules.field_definitions(), "orders": list(rules.ORDERS), "max_limit": rules.MAX_LIMIT}


@router.post("/rules/preview", response_model=RulePreviewOut, summary="Try a rule before saving it")
def rule_preview(body: RulePreviewIn, _user: User = Depends(current_user), db: Database = Depends(get_db)):
    rule = rules.validate(body.rule)
    with db.read() as conn:
        ids = [r[0] for r in conn.execute(rules.query(rule, seed=1))]
        return {"count": len(ids), "tracks": _tracks(conn, ids[:20]), "needs_analysis": rules.uses_analysis(rule)}


@router.get("/tracks/{track_id}/similar", response_model=list[TrackOut], summary="Similar tracks")
def similar(
    track_id: int,
    request: Request,
    limit: int = Query(30, ge=1, le=200),
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        if conn.execute(select(tracks.c.id).where(tracks.c.id == track_id)).first() is None:
            raise NotFound("track not found")
        near = request.app.state.vectors.nearest(conn, track_id, limit)
        ids = [t for t, _ in near] if near else fallback_similar(conn, track_id, limit)
        return _tracks(conn, ids)


@router.get("/tracks/{track_id}/radio", response_model=list[TrackOut], summary="A station starting from a track")
def track_radio(
    track_id: int,
    request: Request,
    limit: int = Query(50, ge=5, le=300),
    _user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        if conn.execute(select(tracks.c.id).where(tracks.c.id == track_id)).first() is None:
            raise NotFound("track not found")
        ids = radio(conn, request.app.state.vectors, track_id, limit, np.random.default_rng())
        return _tracks(conn, ids)


@router.get("/autoplaylists", response_model=list[AutoPlaylistOut], summary="Auto-playlists you can see")
def list_auto(
    status: str | None = Query(None, description="Admins: filter by status"),
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return auto_service.list_auto(conn, user, status if user.is_admin else None)


@router.get("/autoplaylists/{auto_id}", response_model=AutoPlaylistOut)
def get_auto(auto_id: int, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return auto_service.get_auto(conn, user, auto_id)


@router.get("/autoplaylists/{auto_id}/items", response_model=AutoItemsPage)
def auto_items(
    auto_id: int,
    limit: int = Query(300, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        items, total = auto_service.list_items(conn, user, auto_id, limit, offset)
    return {"items": items, "total": total}


@router.post(
    "/autoplaylists/{auto_id}/freeze",
    response_model=PlaylistOut,
    status_code=201,
    summary="Save the current tracks as your own playlist",
)
def freeze(
    auto_id: int, body: FreezeIn, request: Request, user: User = Depends(current_user), db: Database = Depends(get_db)
):
    with db.write() as conn:
        out, event = auto_service.freeze(conn, user, auto_id, body.name)
    request.app.state.bus.publish(event)
    return out


# --- admin ---------------------------------------------------------------------------------


@admin.patch(
    "/autoplaylists/{auto_id}",
    response_model=AutoPlaylistOut,
    summary="Publish, hide, rename, restrict access, change a custom rule",
)
def admin_update(
    auto_id: int, body: AutoUpdate, admin_user: User = Depends(require_admin), db: Database = Depends(get_db)
):
    with db.write() as conn:
        auto_service.admin_update(conn, auto_id, **body.model_dump())
        return auto_service.get_auto(conn, admin_user, auto_id)


@admin.post(
    "/autoplaylists", response_model=AutoPlaylistOut, status_code=201, summary="Create an auto-playlist from a rule"
)
def admin_create(body: AutoCreate, admin_user: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        auto_id = auto_service.admin_create(conn, body.name, body.description, body.rule, body.access)
        return auto_service.get_auto(conn, admin_user, auto_id)


@admin.delete(
    "/autoplaylists/{auto_id}", response_model=Ok, summary="Delete (own rules) or dismiss (generated) an auto-playlist"
)
def admin_delete(auto_id: int, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        auto_service.admin_delete(conn, auto_id)
    return Ok()


@admin.post("/autoplaylists/regenerate", response_model=Ok, status_code=202, summary="Regenerate now")
def admin_regenerate(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        enqueue_autoplaylists(conn)
    return Ok()


@admin.get("/analysis", response_model=AnalysisStatus, summary="Audio analysis progress")
def admin_analysis(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        return analysis_stats(conn)


@admin.post("/analysis/start", response_model=Ok, status_code=202, summary="Analyse pending tracks now")
def admin_analysis_start(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        enqueue_analysis(conn)
    return Ok()


@admin.get("/analysis/failures", response_model=list[AnalysisFailure], summary="Tracks the analysis skipped")
def admin_analysis_failures(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        rows = conn.execute(
            select(
                track_features.c.track_id,
                track_features.c.error,
                (library_roots.c.path + "/" + tracks.c.rel_path).label("path"),
            )
            .join(tracks, tracks.c.id == track_features.c.track_id)
            .join(library_roots, library_roots.c.id == tracks.c.root_id)
            .where(track_features.c.status == "failed", tracks.c.missing_since.is_(None))
            .order_by(track_features.c.analyzed_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    return [AnalysisFailure(track_id=r.track_id, path=r.path, error=r.error) for r in rows]
