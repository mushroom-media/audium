"""Auto-playlists as seen by users and managed by the admin.

Visibility (decided in phase 0):
- the admin sees everything: suggestions, published and dismissed playlists
- users see published playlists with access "all", or "restricted" when they are listed
- "admin_only" and unpublished playlists are invisible to users (404)
Users cannot change auto-playlists; they can save a copy ("freeze") as their own playlist.
"""

import json

from sqlalchemy import Connection, delete, func, insert, select, update

from audium.analysis import autoplaylists, rules
from audium.db.schema import auto_playlist_access, auto_playlist_items, auto_playlists, playlists, track_genres, tracks
from audium.errors import BadRequest, NotFound
from audium.services import playlists as playlist_service
from audium.services.library import track_item, track_select
from audium.services.users import User
from audium.util import now_ms

STATUSES = ("suggested", "published", "dismissed")
ACCESS = ("all", "restricted", "admin_only")


def _can_view(conn: Connection, user: User, row) -> bool:
    if user.is_admin:
        return True
    if row.status != "published":
        return False
    if row.access == "all":
        return True
    if row.access == "restricted":
        return (
            conn.execute(
                select(auto_playlist_access.c.user_id).where(
                    auto_playlist_access.c.auto_playlist_id == row.id, auto_playlist_access.c.user_id == user.id
                )
            ).first()
            is not None
        )
    return False


def _get(conn: Connection, user: User, auto_id: int):
    row = conn.execute(select(auto_playlists).where(auto_playlists.c.id == auto_id)).first()
    if row is None or not _can_view(conn, user, row):
        raise NotFound("auto-playlist not found")
    return row


def _origin(row) -> str:
    """Where a playlist's tracks come from: tags (genre/year tags of the files), features (measured
    tempo, energy, ...), styles (the sound recognition model) or a custom rule."""
    if row.generator == "custom":
        return "custom"
    if row.generator in ("rule", "cluster"):
        return "features"
    return "styles" if row.generator == "sound" or row.key.startswith("style:") else "tags"


def _detected_tracks(conn: Connection, row) -> int | None:
    """For genre playlists: tracks that are in there by a detected genre (they had no genre tag)."""
    if not row.key.startswith(("genre:", "genre-decade:")):
        return None
    detected = select(track_genres.c.track_id).where(track_genres.c.source == "detected")
    return conn.execute(
        select(func.count()).where(
            auto_playlist_items.c.auto_playlist_id == row.id, auto_playlist_items.c.track_id.in_(detected)
        )
    ).scalar_one()


def _out(conn: Connection, row, admin: bool) -> dict:
    out = {
        "id": row.id,
        "key": row.key,
        "generator": row.generator,
        "origin": _origin(row),
        "detected_tracks": _detected_tracks(conn, row),
        "name": row.name,
        "description": row.description,
        "track_count": row.track_count,
        "duration_ms": row.duration_ms,
        "cover": row.cover_hash,
        "generated_at": row.generated_at,
        "rule": json.loads(row.rule_json) if row.rule_json else None,
    }
    if admin:
        out["status"] = row.status
        out["access"] = row.access
        out["user_ids"] = [
            r[0]
            for r in conn.execute(
                select(auto_playlist_access.c.user_id).where(auto_playlist_access.c.auto_playlist_id == row.id)
            )
        ]
    return out


def list_auto(conn: Connection, user: User, status: str | None = None) -> list[dict]:
    q = select(auto_playlists)
    if status:
        if status not in STATUSES:
            raise BadRequest("status must be suggested, published or dismissed")
        q = q.where(auto_playlists.c.status == status)
    elif not user.is_admin:
        q = q.where(auto_playlists.c.status == "published")
    order = {"rule": 0, "cluster": 1, "sound": 1, "custom": 2, "tag": 3}
    rows = [r for r in conn.execute(q) if _can_view(conn, user, r)]
    rows.sort(key=lambda r: (order.get(r.generator, 9), r.key.startswith("genre-decade"), -r.track_count, r.name))
    return [_out(conn, r, user.is_admin) for r in rows]


def get_auto(conn: Connection, user: User, auto_id: int) -> dict:
    return _out(conn, _get(conn, user, auto_id), user.is_admin)


def list_items(conn: Connection, user: User, auto_id: int, limit: int, offset: int):
    row = _get(conn, user, auto_id)
    rows = conn.execute(
        track_select()
        .add_columns(auto_playlist_items.c.reason, auto_playlist_items.c.rank)
        .join(auto_playlist_items, auto_playlist_items.c.track_id == tracks.c.id)
        .where(auto_playlist_items.c.auto_playlist_id == auto_id)
        .order_by(auto_playlist_items.c.rank)
        .limit(limit)
        .offset(offset)
    ).all()
    return [{"reason": r.reason, "track": track_item(r)} for r in rows], row.track_count


def track_ids(conn: Connection, user: User, auto_id: int) -> list[int]:
    _get(conn, user, auto_id)
    return [
        r[0]
        for r in conn.execute(
            select(auto_playlist_items.c.track_id)
            .join(tracks, tracks.c.id == auto_playlist_items.c.track_id)
            .where(auto_playlist_items.c.auto_playlist_id == auto_id, tracks.c.missing_since.is_(None))
            .order_by(auto_playlist_items.c.rank)
        )
    ]


def freeze(conn: Connection, user: User, auto_id: int, name: str | None):
    """Save the current tracks as the user's own playlist (kind frozen_auto)."""
    row = _get(conn, user, auto_id)
    track_ids = [
        r[0]
        for r in conn.execute(
            select(auto_playlist_items.c.track_id)
            .where(auto_playlist_items.c.auto_playlist_id == auto_id)
            .order_by(auto_playlist_items.c.rank)
        )
    ]
    out, event = playlist_service.create_playlist(conn, user, name or row.name, row.description, "private", track_ids)
    conn.execute(update(playlists).where(playlists.c.id == out["id"]).values(kind="frozen_auto"))
    out["kind"] = "frozen_auto"
    return out, event


# --- admin ---------------------------------------------------------------------------------


def admin_update(
    conn: Connection,
    auto_id: int,
    *,
    name: str | None,
    description: str | None,
    status: str | None,
    access: str | None,
    user_ids: list[int] | None,
    rule: dict | None,
) -> None:
    row = conn.execute(select(auto_playlists).where(auto_playlists.c.id == auto_id)).first()
    if row is None:
        raise NotFound("auto-playlist not found")
    values: dict = {"updated_at": now_ms()}
    if name is not None:
        clean = " ".join(name.split())[:200]
        if not clean:
            raise BadRequest("name must not be empty")
        values.update(name=clean, name_locked=True)  # the generator keeps the admin's name
    if description is not None:
        values["description"] = description.strip()[:2000] or None
    if status is not None:
        if status not in STATUSES:
            raise BadRequest("status must be suggested, published or dismissed")
        values["status"] = status
    if access is not None:
        if access not in ACCESS:
            raise BadRequest("access must be all, restricted or admin_only")
        values["access"] = access
    if rule is not None:
        if row.generator != "custom":
            raise BadRequest("only custom auto-playlists have an editable rule")
        values["rule_json"] = json.dumps(rules.validate(rule))
    conn.execute(update(auto_playlists).where(auto_playlists.c.id == auto_id).values(**values))
    if rule is not None:
        autoplaylists.refresh_custom(conn, auto_id)
    if user_ids is not None:
        conn.execute(delete(auto_playlist_access).where(auto_playlist_access.c.auto_playlist_id == auto_id))
        if user_ids:
            conn.execute(
                insert(auto_playlist_access),
                [{"auto_playlist_id": auto_id, "user_id": u} for u in sorted(set(user_ids))],
            )
    if status == "dismissed":
        conn.execute(delete(auto_playlist_items).where(auto_playlist_items.c.auto_playlist_id == auto_id))
        conn.execute(update(auto_playlists).where(auto_playlists.c.id == auto_id).values(track_count=0))


def admin_create(conn: Connection, name: str, description: str | None, rule: dict, access: str) -> int:
    rule = rules.validate(rule)
    if access not in ACCESS:
        raise BadRequest("access must be all, restricted or admin_only")
    clean = " ".join(name.split())[:200]
    if not clean:
        raise BadRequest("name must not be empty")
    ts = now_ms()
    next_id = conn.execute(select(func.coalesce(func.max(auto_playlists.c.id), 0) + 1)).scalar_one()
    auto_id = conn.execute(
        insert(auto_playlists).values(
            key=f"custom:{next_id}:{ts}",
            generator="custom",
            name=clean,
            name_locked=True,
            description=(description or "").strip() or None,
            rule_json=json.dumps(rule),
            status="published",
            access=access,
            created_at=ts,
            updated_at=ts,
        )
    ).inserted_primary_key[0]
    autoplaylists.refresh_custom(conn, auto_id)  # filled right away, not at the next generator run
    return auto_id


def admin_delete(conn: Connection, auto_id: int) -> None:
    """Custom playlists are deleted; generated ones are dismissed so they do not come back."""
    row = conn.execute(select(auto_playlists).where(auto_playlists.c.id == auto_id)).first()
    if row is None:
        raise NotFound("auto-playlist not found")
    if row.generator == "custom":
        conn.execute(delete(auto_playlists).where(auto_playlists.c.id == auto_id))
    else:
        admin_update(
            conn, auto_id, name=None, description=None, status="dismissed", access=None, user_ids=None, rule=None
        )
