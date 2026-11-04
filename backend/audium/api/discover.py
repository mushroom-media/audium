"""Auto-playlists, rules, similar tracks and radio."""

from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select

from audium.analysis import autoplaylists, rules, sources, taste, why
from audium.analysis.similarity import Blend, blend, group_radio, radio
from audium.analysis.tasks import analysis_stats, enqueue_analysis, enqueue_autoplaylists
from audium.api.deps import current_user, get_db, get_settings, require_admin, viewer
from audium.api.library_models import TrackOut
from audium.api.models import Ok
from audium.api.playlist_models import PlaylistOut
from audium.config import Settings
from audium.db.engine import Database
from audium.db.pagination import fetch_ordered
from audium.db.schema import artist_similar, genres, library_roots, styles, track_artists, track_features, tracks
from audium.db.state import set_state
from audium.errors import NotFound
from audium.i18n import tr, user_language
from audium.services import auto as auto_service
from audium.services import discover as discover_service
from audium.services import similar_artists
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
    generator: str = Field(description="tag | rule | cluster | sound | custom")
    origin: str = Field(
        description="tags (genre/year tags) | features (tempo, energy, ...) | styles (sound recognition) | custom"
    )
    detected_tracks: int | None = Field(
        None, description="Genre playlists: tracks in there by a detected genre because they had no genre tag"
    )
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


class FamilyOut(BaseModel):
    name: str = Field(description='Broad genre, e.g. "Rock"')
    playlist: AutoPlaylistOut = Field(description="All tracks of the family")
    genres: list[AutoPlaylistOut] = Field(description="Its genre playlists, biggest first")
    plays: int = Field(description="Your plays in it over the last 90 days")


class GenreOverviewOut(BaseModel):
    families: list[FamilyOut] = Field(description="Most played by you first, then the biggest")
    others: list[AutoPlaylistOut] = Field(description="Genre playlists that belong to no family")


class RediscoverOut(BaseModel):
    type: Literal["album", "artist"]
    id: int
    name: str
    subtitle: str | None
    cover: str | None
    last_played: int = Field(description="Your last play of it (ms)")


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


class AutoSource(BaseModel):
    source: Literal["all", "sound"] = Field(
        description="all: tags, audio features and sound recognition | sound: only sound recognition"
        " (detected styles and mixes over the sound fingerprints)"
    )


class AnalysisStatus(BaseModel):
    backend: str = Field(description="essentia[+effnet][+moods] | none | unknown")
    waiting: str | None = Field(description='Why it may not run now: "paused", "window" (time window), or null')
    cpus: int = Field(description="CPU cores of the server")
    workers_default: int = Field(description="Processes for the setting 'default' (AUDIUM_ANALYSIS_WORKERS)")
    server_time: str = Field(description="HH:MM on the server's clock, which the time window uses")
    tracks: int
    analyzed: int
    failed: int
    pending: int
    fingerprints: int = Field(description="Tracks with a sound fingerprint (style detection), radio uses these")
    styles: int = Field(description="Tracks with at least one detected style")


class AnalysisFailure(BaseModel):
    track_id: int
    path: str
    error: str | None


class StationTrackOut(TrackOut):
    reason: str | None = Field(
        None, description='Admins only: why the track is in here, e.g. "Klingt ähnlich 70 % · Genre: Rock 30 %"'
    )


class SourceIn(BaseModel):
    on: bool | None = None
    weight: int | None = Field(None, ge=sources.MIN_WEIGHT, le=sources.MAX_WEIGHT)


class SourceOut(BaseModel):
    on: bool
    weight: int


class SourcesOut(BaseModel):
    sources: dict[str, SourceOut] = Field(description="sound | features | genre | artists | taste")
    options: dict[str, bool] = Field(description="smooth_tempo: avoid big tempo jumps between tracks")
    artists_pending: int = Field(description="Artists not yet asked for at ListenBrainz (while 'artists' is on)")
    artists_known: int = Field(description="Artists with similar artists from ListenBrainz")


def _tracks(conn, ids: list[int]) -> list[dict]:
    return [track_item(r) for r in fetch_ordered(conn, track_select(), tracks.c.id, ids)]


def _station(conn, station: Blend, user: User, own: str = "Eigener Titel") -> list[dict]:
    """The station's tracks; admins also get why each one is in there."""
    items = _tracks(conn, [t for t, _ in station.picks])
    if user.is_admin:
        reasons = why.describe(conn, station, own, user_language(conn, user.id))
        items = [{**item, "reason": reasons.get(item["id"])} for item in items]
    return items


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


class StyleOut(BaseModel):
    name: str
    genre: str | None = Field(description="The genre this style counts for")
    track_count: int


@router.get("/styles", response_model=list[StyleOut], summary="Detected styles with track counts")
def list_styles(_user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        rows = conn.execute(
            select(styles.c.name, styles.c.genre, styles.c.track_count)
            .where(styles.c.track_count > 0)
            .order_by(styles.c.track_count.desc(), styles.c.name)
        ).all()
    return [StyleOut(**r._mapping) for r in rows]


@router.get("/rules/fields", summary="Fields, operators and values for the rule editor")
def rule_fields(user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        lang = user_language(conn, user.id)
    return {"fields": rules.field_definitions(lang), "orders": list(rules.ORDERS), "max_limit": rules.MAX_LIMIT}


@router.post("/rules/preview", response_model=RulePreviewOut, summary="Try a rule before saving it")
def rule_preview(body: RulePreviewIn, _user: User = Depends(current_user), db: Database = Depends(get_db)):
    rule = rules.validate(body.rule)
    with db.read() as conn:
        ids = [r[0] for r in conn.execute(rules.query(rule, seed=1))]
        return {"count": len(ids), "tracks": _tracks(conn, ids[:20]), "needs_analysis": rules.uses_analysis(rule)}


@router.get("/tracks/{track_id}/similar", response_model=list[StationTrackOut], summary="Similar tracks")
def similar(
    track_id: int,
    request: Request,
    limit: int = Query(30, ge=1, le=200),
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        if conn.execute(select(tracks.c.id).where(tracks.c.id == track_id)).first() is None:
            raise NotFound("track not found")
        return _station(conn, blend(conn, request.app.state.vectors, [track_id], limit, user.id), user)


# Continuing a station: the tracks it already played (only the latest MAX_EXCLUDE count).
MAX_EXCLUDE = 500
EXCLUDE = Query([], description="Track ids the station already played: continue it without them")


@router.get("/tracks/{track_id}/radio", response_model=list[StationTrackOut], summary="A station starting from a track")
def track_radio(
    track_id: int,
    request: Request,
    limit: int = Query(50, ge=5, le=300),
    exclude: list[int] = EXCLUDE,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        if conn.execute(select(tracks.c.id).where(tracks.c.id == track_id)).first() is None:
            raise NotFound("track not found")
        rng = np.random.default_rng()
        return _station(
            conn, radio(conn, request.app.state.vectors, track_id, limit, rng, exclude[-MAX_EXCLUDE:], user.id), user
        )


def _group_radio(
    conn, request: Request, user: User, members, limit: int, exclude: list[int], what: str, item_id: int
) -> list[dict]:
    seeds = list(conn.execute(select(tracks.c.id).where(members, tracks.c.missing_since.is_(None))).scalars())
    if not seeds:
        raise NotFound(f"{what} not found")
    rng = np.random.default_rng()
    station = group_radio(
        conn, request.app.state.vectors, seeds, limit, rng, exclude[-MAX_EXCLUDE:], user.id, f"{what}:{item_id}"
    )
    return _station(conn, station, user, "Vom Album" if what == "album" else "Vom Künstler")


@router.get(
    "/albums/{album_id}/radio",
    response_model=list[StationTrackOut],
    summary="A station from an album: similar music, about a quarter from the album itself",
)
def album_radio(
    album_id: int,
    request: Request,
    limit: int = Query(50, ge=5, le=300),
    exclude: list[int] = EXCLUDE,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        return _group_radio(conn, request, user, tracks.c.album_id == album_id, limit, exclude, "album", album_id)


@router.get(
    "/artists/{artist_id}/radio",
    response_model=list[StationTrackOut],
    summary="A station from an artist: similar music, about a quarter by the artist",
)
def artist_radio(
    artist_id: int,
    request: Request,
    limit: int = Query(50, ge=5, le=300),
    exclude: list[int] = EXCLUDE,
    user: User = Depends(current_user),
    db: Database = Depends(get_db),
):
    by_artist = exists().where(track_artists.c.track_id == tracks.c.id, track_artists.c.artist_id == artist_id)
    with db.read() as conn:
        return _group_radio(conn, request, user, by_artist, limit, exclude, "artist", artist_id)


class RadioSkipIn(BaseModel):
    track_id: int
    station: str = Field(description='The station it was skipped in: "track:3", "album:5" or "artist:2"')


@router.post(
    "/radio/skips",
    response_model=Ok,
    summary="A track skipped early in a radio station: it ranks lower in stations like that one",
)
def radio_skip(body: RadioSkipIn, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        taste.record_skip(conn, user.id, body.track_id, body.station)
    return {"ok": True}


@router.post(
    "/radio/dislikes",
    response_model=Ok,
    summary='A track marked "Mag ich nicht" in a radio station: it stays out of that one, ranks lower in those like it',
)
def radio_dislike(body: RadioSkipIn, user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.write() as conn:
        taste.record_skip(conn, user.id, body.track_id, body.station, disliked=True)
    return {"ok": True}


@router.get("/discover/genres", response_model=GenreOverviewOut, summary="Broad genres with their genre playlists")
def discover_genres(user: User = Depends(current_user), db: Database = Depends(get_db)):
    with db.read() as conn:
        return discover_service.genre_overview(conn, user)


@router.get(
    "/discover/rediscover",
    response_model=list[RediscoverOut],
    summary="Albums and artists you have not played for a while",
)
def discover_rediscover(
    limit: int = Query(8, ge=1, le=24), user: User = Depends(viewer), db: Database = Depends(get_db)
):
    with db.read() as conn:
        lang = user_language(conn, user.id)
        items = discover_service.rediscover(conn, user, limit)
    return [{**item, "subtitle": tr(lang, item["subtitle"])} if item["type"] == "artist" else item for item in items]


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


@admin.get("/autoplaylists/source", response_model=AutoSource, summary="What auto-playlists are made from")
def admin_source(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        return AutoSource(source=autoplaylists.source(conn))


@admin.put("/autoplaylists/source", response_model=AutoSource, summary="Change the source and regenerate")
def admin_set_source(body: AutoSource, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        if autoplaylists.source(conn) != body.source:
            set_state(conn, autoplaylists.SOURCE_STATE, body.source)
            enqueue_autoplaylists(conn)
    return body


def _sources_out(conn) -> SourcesOut:
    cfg = sources.load(conn)
    return SourcesOut(
        sources={n: SourceOut(on=s.on, weight=s.weight) for n, s in cfg.items()},
        artists_pending=similar_artists.count_pending(conn) if cfg["artists"].on else 0,
        artists_known=conn.execute(select(func.count(func.distinct(artist_similar.c.artist_id)))).scalar_one(),
        options=sources.options(conn),
    )


class RadioOptionsIn(BaseModel):
    smooth_tempo: bool | None = None


@admin.patch("/radio/options", response_model=SourcesOut, summary="Further station options (tempo)")
def admin_set_radio_options(
    body: RadioOptionsIn, _admin: User = Depends(require_admin), db: Database = Depends(get_db)
):
    with db.write() as conn:
        sources.save_options(conn, body.model_dump(exclude_none=True))
        return _sources_out(conn)


@admin.get("/radio/sources", response_model=SourcesOut, summary="What stations and mixes are made from")
def admin_sources(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        return _sources_out(conn)


@admin.patch(
    "/radio/sources",
    response_model=SourcesOut,
    summary="Switch sources on/off and weight them; at least one stays on",
)
def admin_set_sources(body: dict[str, SourceIn], _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        _after, switched = sources.save(conn, {n: s.model_dump(exclude_none=True) for n, s in body.items()})
        if "artists" in switched and similar_artists.enabled(conn):
            similar_artists.enqueue(conn)
        if switched & {"sound", "features"}:
            enqueue_autoplaylists(conn)  # mixes over that space come or go
        return _sources_out(conn)


@admin.get("/analysis", response_model=AnalysisStatus, summary="Audio analysis progress")
def admin_analysis(
    _admin: User = Depends(require_admin), db: Database = Depends(get_db), settings: Settings = Depends(get_settings)
):
    with db.read() as conn:
        return {**analysis_stats(conn), "workers_default": max(1, settings.analysis_workers)}


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
