import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from audium.analysis.tasks import analysis_blocked, enqueue_analysis
from audium.api.deps import get_db, get_settings, require_admin
from audium.api.library_models import (
    BrowseOut,
    ExcludeCreate,
    ExcludeOut,
    JobOut,
    LibraryStats,
    RootCreate,
    RootOut,
    RootUpdate,
    ScanRequest,
)
from audium.api.models import Interfaces, Ok, Page, ServerSettings, ServerSettingsUpdate
from audium.config import Settings
from audium.db.engine import Database
from audium.db.pagination import Sort, fetch_ordered, page_ids
from audium.db.schema import albums, artists, jobs, tracks
from audium.db.state import bump_library_generation
from audium.errors import NotFound
from audium.jobs import queue as jobq
from audium.scanner.tasks import enqueue_scan
from audium.services import roots as root_service
from audium.services import server_settings as server_settings_service
from audium.services.users import User

router = APIRouter(prefix="/admin", tags=["admin: library"])

_JOB_SORT = Sort("id", (jobs.c.id,), default_desc=True)


def _job_out(row) -> JobOut:
    return JobOut(
        **{k: v for k, v in row._mapping.items() if k in JobOut.model_fields},
        result=json.loads(row.result_json) if row.result_json else None,
    )


@router.get("/roots", response_model=list[RootOut], summary="Library folders")
def list_roots(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        return [RootOut(**r._mapping) for r in root_service.list_roots(conn)]


@router.post(
    "/roots",
    response_model=RootOut,
    status_code=201,
    summary="Add a library folder (must be inside the music mount)",
)
def add_root(
    body: RootCreate,
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        row = root_service.add_root(conn, settings, body.path)
        enqueue_scan(conn, [row.id])
    return RootOut(**row._mapping)


@router.patch("/roots/{root_id}", response_model=RootOut, summary="Enable or disable a library folder")
def update_root(root_id: int, body: RootUpdate, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        row = root_service.set_enabled(conn, root_id, body.enabled)
        if body.enabled:
            enqueue_scan(conn, [root_id])
    return RootOut(**row._mapping)


@router.get("/roots/{root_id}/excludes", response_model=list[ExcludeOut])
def list_excludes(root_id: int, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        return [ExcludeOut(**r._mapping) for r in root_service.list_excludes(conn, root_id)]


@router.post(
    "/roots/{root_id}/excludes",
    response_model=ExcludeOut,
    status_code=201,
    summary="Exclude a sub-folder from scanning",
)
def add_exclude(
    root_id: int,
    body: ExcludeCreate,
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.write() as conn:
        row = root_service.add_exclude(conn, settings, root_id, body.rel_path)
        enqueue_scan(conn, [root_id])
    return ExcludeOut(**row._mapping)


@router.delete("/roots/{root_id}/excludes/{exclude_id}", response_model=Ok)
def remove_exclude(
    root_id: int, exclude_id: int, _admin: User = Depends(require_admin), db: Database = Depends(get_db)
):
    with db.write() as conn:
        root_service.remove_exclude(conn, root_id, exclude_id)
        enqueue_scan(conn, [root_id])
    return Ok()


@router.get("/browse", response_model=BrowseOut, summary="Folders inside the music mount (folder picker)")
def browse(
    path: str | None = Query(None, max_length=4096),
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    with db.read() as conn:
        return root_service.browse(conn, settings, path)


@router.post("/scan", response_model=JobOut, status_code=202, summary="Start a library scan")
def start_scan(body: ScanRequest, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        job_id = enqueue_scan(conn, body.root_ids, body.force)
        row = conn.execute(select(jobs).where(jobs.c.id == job_id)).first()
    return _job_out(row)


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(
    status: Literal["queued", "running", "done", "failed", "cancelled"] | None = None,
    queue: str | None = Query(None, max_length=32),
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    base = select(jobs.c.id)
    if status:
        base = base.where(jobs.c.status == status)
    if queue:
        base = base.where(jobs.c.queue == queue)
    with db.read() as conn:
        ids, next_cursor = page_ids(conn, base, _JOB_SORT, True, cursor, 0, limit)
        rows = fetch_ordered(conn, select(jobs), jobs.c.id, ids)
    return Page[JobOut](items=[_job_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == job_id)).first()
    if row is None:
        raise NotFound("job not found")
    return _job_out(row)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        if jobq.request_cancel(conn, job_id) is None:
            raise NotFound("job not found")
        row = conn.execute(select(jobs).where(jobs.c.id == job_id)).first()
    return _job_out(row)


@router.get("/settings", response_model=ServerSettings, summary="Server-wide settings")
def server_settings(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        return server_settings_service.get_server_settings(conn)


@router.patch("/settings", response_model=ServerSettings)
def update_server_settings(
    body: ServerSettingsUpdate, _admin: User = Depends(require_admin), db: Database = Depends(get_db)
):
    with db.write() as conn:
        merged, changed = server_settings_service.update_server_settings(conn, body.model_dump(exclude_none=True))
        if "artist_album_covers" in changed:
            bump_library_generation(conn)  # artist pictures change for users who follow the server
        if "artist_folder_images" in changed:
            enqueue_scan(conn)  # picks the artist pictures anew (unchanged tracks are skipped)
        if any(k.startswith("analysis_") for k in changed) and analysis_blocked(conn) is None:
            enqueue_analysis(conn)  # resumes at once (a running analysis picks up the new settings itself)
    return merged


@router.get("/interfaces", response_model=Interfaces, summary="What the environment allows of the interfaces")
def interfaces(_admin: User = Depends(require_admin), settings: Settings = Depends(get_settings)):
    return Interfaces(
        subsonic_available=settings.subsonic_enabled,
        model_download_available=settings.analysis_download_models,
        app_origins=settings.app_origin_list,
    )


@router.get("/stats", response_model=LibraryStats)
def stats(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        present = tracks.c.missing_since.is_(None)
        track_count, duration = conn.execute(
            select(func.count(), func.coalesce(func.sum(tracks.c.duration_ms), 0)).where(present)
        ).one()
        missing = conn.execute(select(func.count()).where(tracks.c.missing_since.is_not(None))).scalar_one()
        album_count = conn.execute(select(func.count()).where(albums.c.track_count > 0)).scalar_one()
        artist_count = conn.execute(
            select(func.count()).where((artists.c.track_count > 0) | (artists.c.album_count > 0))
        ).scalar_one()
        status_rows = conn.execute(
            select(tracks.c.tag_status, func.count()).where(present).group_by(tracks.c.tag_status)
        ).all()
    return LibraryStats(
        tracks=track_count,
        albums=album_count,
        artists=artist_count,
        missing_tracks=missing,
        duration_ms=duration,
        tag_status={s: n for s, n in status_rows},
    )
