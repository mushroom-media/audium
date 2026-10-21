"""Playlists: CRUD, items, sharing.

Ordering: items carry a server-assigned integer `position` with gaps (GAP apart). Inserting
between two items picks a free integer between their positions; when there is none left the
playlist is renumbered inside the same transaction. Clients never compute positions, they say
"after item X". Because every write runs in one serialized SQLite transaction, two editors
inserting at the same spot both succeed, one after the other, and no edit is lost.

Every change bumps `version` and writes a row to playlist_events. The API layer pushes those
rows to connected clients (SSE) after the commit; clients that missed some catch up from the
table with Last-Event-ID.
"""

import json
from dataclasses import dataclass

from sqlalchemy import Connection, and_, case, delete, func, insert, or_, select, update

from audium.db.schema import covers, playlist_events, playlist_items, playlist_shares, playlists, tracks, users
from audium.errors import BadRequest, Conflict, NotFound
from audium.services.library import track_item, track_select
from audium.services.permissions import playlist_role, require_playlist
from audium.services.users import User
from audium.util import now_ms

GAP = 1024
MAX_ITEMS = 20_000
MAX_ADD = 5_000
VISIBILITIES = ("private", "users")
SHARE_ROLES = ("viewer", "editor")
_EVENT_RETENTION_MS = 7 * 86_400_000


@dataclass(frozen=True)
class Event:
    seq: int
    playlist_id: int
    type: str  # created | updated | items | shares | deleted
    version: int
    actor_id: int | None
    recipients: list[int] | str  # user ids, or "*"

    def visible_to(self, user_id: int) -> bool:
        return self.recipients == "*" or user_id in self.recipients


# --- helpers -------------------------------------------------------------------------------


def _clean_name(name: str) -> str:
    n = " ".join(name.split())[:200]
    if not n:
        raise BadRequest("name must not be empty")
    return n


def _check_version(row, if_version: int | None) -> None:
    if if_version is not None and if_version != row.version:
        raise Conflict("the playlist was changed meanwhile", version=row.version)


def _recipients(conn: Connection, playlist_id: int, owner_id: int, visibility: str, extra=()) -> list[int] | str:
    if visibility == "users":
        return "*"
    ids = {owner_id, *extra}
    ids.update(
        r[0]
        for r in conn.execute(select(playlist_shares.c.user_id).where(playlist_shares.c.playlist_id == playlist_id))
    )
    return sorted(ids)


def _event(conn: Connection, row, type_: str, actor: User, recipients=None) -> Event:
    version = row.version
    rec = recipients if recipients is not None else _recipients(conn, row.id, row.owner_id, row.visibility)
    seq = conn.execute(
        insert(playlist_events).values(
            playlist_id=row.id,
            type=type_,
            actor_id=actor.id,
            version=version,
            recipients_json=json.dumps(rec),
            at=now_ms(),
        )
    ).inserted_primary_key[0]
    return Event(seq, row.id, type_, version, actor.id, rec)


def _touch(conn: Connection, playlist_id: int, *, items_changed: bool):
    """Bump the version (and recompute the cached item stats); returns the fresh row."""
    values: dict = {"version": playlists.c.version + 1, "updated_at": now_ms()}
    if items_changed:
        stats = conn.execute(
            select(func.count(), func.coalesce(func.sum(tracks.c.duration_ms), 0))
            .select_from(playlist_items.join(tracks, tracks.c.id == playlist_items.c.track_id))
            .where(playlist_items.c.playlist_id == playlist_id)
        ).one()
        first_cover = conn.execute(
            select(covers.c.hash)
            .select_from(
                playlist_items.join(tracks, tracks.c.id == playlist_items.c.track_id).join(
                    covers, covers.c.id == tracks.c.cover_id
                )
            )
            .where(playlist_items.c.playlist_id == playlist_id)
            .order_by(playlist_items.c.position, playlist_items.c.id)
            .limit(1)
        ).scalar()
        values.update(item_count=stats[0], duration_ms=stats[1], cover_hash=first_cover)
    conn.execute(update(playlists).where(playlists.c.id == playlist_id).values(**values))
    return conn.execute(select(playlists).where(playlists.c.id == playlist_id)).one()


def _existing_track_ids(conn: Connection, track_ids: list[int]) -> list[int]:
    found: set[int] = set()
    for i in range(0, len(track_ids), 500):
        chunk = track_ids[i : i + 500]
        found.update(r[0] for r in conn.execute(select(tracks.c.id).where(tracks.c.id.in_(chunk))))
    return [t for t in track_ids if t in found]


# --- reading -------------------------------------------------------------------------------


def playlist_out(conn: Connection, row, role: str) -> dict:
    owner = conn.execute(select(users.c.username, users.c.display_name).where(users.c.id == row.owner_id)).first()
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "visibility": row.visibility,
        "kind": row.kind,
        "owner": {"id": row.owner_id, "username": owner.username, "display_name": owner.display_name},
        "role": role,
        "version": row.version,
        "item_count": row.item_count,
        "duration_ms": row.duration_ms,
        "cover": row.cover_hash,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_playlists(conn: Connection, user: User, scope: str, limit: int, offset: int) -> list[dict]:
    """scope: mine (owned), shared (shared with me), public (visible to all, not mine), all."""
    share = playlist_shares.alias("s")
    role = case(
        (playlists.c.owner_id == user.id, "owner"),
        (share.c.role.is_not(None), share.c.role),
        else_="viewer",
    ).label("role")
    stmt = select(playlists, role).outerjoin(
        share, and_(share.c.playlist_id == playlists.c.id, share.c.user_id == user.id)
    )
    if scope == "mine":
        stmt = stmt.where(playlists.c.owner_id == user.id)
    elif scope == "shared":
        stmt = stmt.where(share.c.user_id.is_not(None), playlists.c.owner_id != user.id)
    elif scope == "public":
        stmt = stmt.where(playlists.c.visibility == "users", playlists.c.owner_id != user.id, share.c.user_id.is_(None))
    elif scope == "all":
        stmt = stmt.where(
            or_(playlists.c.owner_id == user.id, share.c.user_id.is_not(None), playlists.c.visibility == "users")
        )
    else:
        raise BadRequest("scope must be mine, shared, public or all")
    rows = conn.execute(stmt.order_by(func.lower(playlists.c.name), playlists.c.id).limit(limit).offset(offset))
    return [playlist_out(conn, r, r.role) for r in rows]


def get_playlist(conn: Connection, user: User, playlist_id: int) -> dict:
    row, role = require_playlist(conn, user, playlist_id, "view")
    return playlist_out(conn, row, role)


def list_items(conn: Connection, user: User, playlist_id: int, limit: int, offset: int):
    require_playlist(conn, user, playlist_id, "view")
    rows = conn.execute(
        track_select()
        .add_columns(
            playlist_items.c.id.label("item_id"),
            playlist_items.c.added_by,
            playlist_items.c.added_at,
            tracks.c.missing_since,
        )
        .join(playlist_items, playlist_items.c.track_id == tracks.c.id)
        .where(playlist_items.c.playlist_id == playlist_id)
        .order_by(playlist_items.c.position, playlist_items.c.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = conn.execute(
        select(func.count()).select_from(playlist_items).where(playlist_items.c.playlist_id == playlist_id)
    ).scalar_one()
    items = [
        {
            "item_id": r.item_id,
            "added_by": r.added_by,
            "added_at": r.added_at,
            "available": r.missing_since is None,
            "track": track_item(r),
        }
        for r in rows
    ]
    return items, total


# --- writing -------------------------------------------------------------------------------


def create_playlist(
    conn: Connection, user: User, name: str, description: str | None, visibility: str, track_ids: list[int]
):
    if visibility not in VISIBILITIES:
        raise BadRequest("visibility must be private or users")
    ts = now_ms()
    playlist_id = conn.execute(
        insert(playlists).values(
            owner_id=user.id,
            name=_clean_name(name),
            description=(description or "").strip()[:2000] or None,
            visibility=visibility,
            kind="manual",
            version=1,
            created_at=ts,
            updated_at=ts,
        )
    ).inserted_primary_key[0]
    if track_ids:
        _insert_items(conn, playlist_id, user, track_ids, after_item_id=None, at_end=True)
        row = _touch(conn, playlist_id, items_changed=True)
    else:
        row = conn.execute(select(playlists).where(playlists.c.id == playlist_id)).one()
    return playlist_out(conn, row, "owner"), _event(conn, row, "created", user)


def update_playlist(
    conn: Connection,
    user: User,
    playlist_id: int,
    *,
    name: str | None,
    description: str | None,
    visibility: str | None,
    if_version: int | None = None,
):
    row, _ = require_playlist(conn, user, playlist_id, "manage")
    _check_version(row, if_version)
    values: dict = {}
    if name is not None:
        values["name"] = _clean_name(name)
    if description is not None:
        values["description"] = description.strip()[:2000] or None
    if visibility is not None:
        if visibility not in VISIBILITIES:
            raise BadRequest("visibility must be private or users")
        values["visibility"] = visibility
    if not values:
        return playlist_out(conn, row, "owner"), None
    # Recipients before the change too: someone losing access must hear about it.
    before = _recipients(conn, row.id, row.owner_id, row.visibility)
    conn.execute(update(playlists).where(playlists.c.id == playlist_id).values(**values))
    new = _touch(conn, playlist_id, items_changed=False)
    after = _recipients(conn, new.id, new.owner_id, new.visibility)
    rec = "*" if "*" in (before, after) else sorted({*before, *after})
    return playlist_out(conn, new, "owner"), _event(conn, new, "updated", user, rec)


def delete_playlist(conn: Connection, user: User, playlist_id: int) -> Event:
    row, _ = require_playlist(conn, user, playlist_id, "manage")
    rec = _recipients(conn, row.id, row.owner_id, row.visibility)
    event = _event(conn, row, "deleted", user, rec)
    conn.execute(delete(playlists).where(playlists.c.id == playlist_id))
    return event


def _ordered_positions(conn: Connection, playlist_id: int, exclude: set[int] = frozenset()):
    rows = conn.execute(
        select(playlist_items.c.id, playlist_items.c.position)
        .where(playlist_items.c.playlist_id == playlist_id)
        .order_by(playlist_items.c.position, playlist_items.c.id)
    ).all()
    return [(r.id, r.position) for r in rows if r.id not in exclude]


def _renumber(conn: Connection, playlist_id: int) -> None:
    for i, (item_id, _pos) in enumerate(_ordered_positions(conn, playlist_id), start=1):
        conn.execute(update(playlist_items).where(playlist_items.c.id == item_id).values(position=i * GAP))


def _slot(
    conn: Connection, playlist_id: int, after_item_id: int | None, at_end: bool, n: int, exclude: set[int] = frozenset()
) -> list[int]:
    """n increasing free positions right after `after_item_id` (None = at the start, or at the
    end when `at_end`). Renumbers once if the gap is too small."""
    for attempt in range(2):
        order = _ordered_positions(conn, playlist_id, exclude)
        if at_end:
            lo = order[-1][1] if order else 0
            return [lo + GAP * (i + 1) for i in range(n)]
        if after_item_id is None:
            idx = -1
        else:
            idx = next((i for i, (item_id, _) in enumerate(order) if item_id == after_item_id), None)
            if idx is None:
                raise NotFound("after_item_id is not in this playlist")
        lo = order[idx][1] if idx >= 0 else None
        hi = order[idx + 1][1] if idx + 1 < len(order) else None
        if hi is None:
            base = lo if lo is not None else 0
            return [base + GAP * (i + 1) for i in range(n)]
        if lo is None:
            lo = hi - GAP * (n + 1)
        if hi - lo - 1 >= n:
            step = (hi - lo) / (n + 1)
            return [lo + int(step * (i + 1)) for i in range(n)]  # step >= 1: strictly increasing, < hi
        if attempt == 0:
            _renumber(conn, playlist_id)
    raise Conflict("could not find a position")  # pragma: no cover - renumbering always makes room


def _insert_items(conn, playlist_id, user, track_ids, after_item_id, at_end) -> list[int]:
    track_ids = _existing_track_ids(conn, track_ids)
    if not track_ids:
        return []
    count = conn.execute(
        select(func.count()).select_from(playlist_items).where(playlist_items.c.playlist_id == playlist_id)
    ).scalar_one()
    if count + len(track_ids) > MAX_ITEMS:
        raise BadRequest(f"a playlist can hold at most {MAX_ITEMS} tracks")
    positions = _slot(conn, playlist_id, after_item_id, at_end, len(track_ids))
    ts = now_ms()
    result = conn.execute(
        insert(playlist_items).returning(playlist_items.c.id, sort_by_parameter_order=True),
        [
            {"playlist_id": playlist_id, "track_id": t, "position": p, "added_by": user.id, "added_at": ts}
            for t, p in zip(track_ids, positions, strict=True)
        ],
    )
    return [r.id for r in result]


def add_items(
    conn: Connection,
    user: User,
    playlist_id: int,
    track_ids: list[int],
    *,
    after_item_id: int | None = None,
    at_end: bool = True,
    if_version: int | None = None,
):
    if not track_ids:
        raise BadRequest("track_ids must not be empty")
    if len(track_ids) > MAX_ADD:
        raise BadRequest(f"at most {MAX_ADD} tracks per request")
    row, _ = require_playlist(conn, user, playlist_id, "edit")
    _check_version(row, if_version)
    item_ids = _insert_items(conn, playlist_id, user, track_ids, after_item_id, at_end)
    if not item_ids:
        raise BadRequest("none of the tracks exist")
    new = _touch(conn, playlist_id, items_changed=True)
    return item_ids, new.version, _event(conn, new, "items", user)


def remove_items(conn: Connection, user: User, playlist_id: int, item_ids: list[int], if_version: int | None = None):
    row, _ = require_playlist(conn, user, playlist_id, "edit")
    _check_version(row, if_version)
    # Removing an item someone else already removed is fine: the result is the same.
    conn.execute(
        delete(playlist_items).where(playlist_items.c.playlist_id == playlist_id, playlist_items.c.id.in_(item_ids))
    )
    new = _touch(conn, playlist_id, items_changed=True)
    return new.version, _event(conn, new, "items", user)


def move_item(
    conn: Connection,
    user: User,
    playlist_id: int,
    item_id: int,
    after_item_id: int | None,
    if_version: int | None = None,
):
    row, _ = require_playlist(conn, user, playlist_id, "edit")
    _check_version(row, if_version)
    exists = conn.execute(
        select(playlist_items.c.id).where(playlist_items.c.id == item_id, playlist_items.c.playlist_id == playlist_id)
    ).scalar()
    if exists is None:
        raise NotFound("item not found")
    if after_item_id == item_id:
        raise BadRequest("an item cannot be moved after itself")
    (position,) = _slot(conn, playlist_id, after_item_id, False, 1, exclude={item_id})
    conn.execute(update(playlist_items).where(playlist_items.c.id == item_id).values(position=position))
    new = _touch(conn, playlist_id, items_changed=True)
    return new.version, _event(conn, new, "items", user)


# --- sharing -------------------------------------------------------------------------------


def list_shares(conn: Connection, user: User, playlist_id: int) -> list[dict]:
    require_playlist(conn, user, playlist_id, "view")
    rows = conn.execute(
        select(playlist_shares.c.user_id, playlist_shares.c.role, users.c.username, users.c.display_name)
        .join(users, users.c.id == playlist_shares.c.user_id)
        .where(playlist_shares.c.playlist_id == playlist_id)
        .order_by(users.c.username)
    ).all()
    return [
        {"user": {"id": r.user_id, "username": r.username, "display_name": r.display_name}, "role": r.role}
        for r in rows
    ]


def set_share(conn: Connection, user: User, playlist_id: int, target_user_id: int, role: str):
    row, _ = require_playlist(conn, user, playlist_id, "manage")
    if role not in SHARE_ROLES:
        raise BadRequest("role must be viewer or editor")
    if target_user_id == row.owner_id:
        raise BadRequest("the owner already has full access")
    target = conn.execute(select(users.c.status).where(users.c.id == target_user_id)).scalar()
    if target is None:
        raise NotFound("user not found")
    updated = conn.execute(
        update(playlist_shares)
        .where(playlist_shares.c.playlist_id == playlist_id, playlist_shares.c.user_id == target_user_id)
        .values(role=role)
    ).rowcount
    if not updated:
        conn.execute(
            insert(playlist_shares).values(
                playlist_id=playlist_id, user_id=target_user_id, role=role, created_at=now_ms()
            )
        )
    new = _touch(conn, playlist_id, items_changed=False)
    return list_shares(conn, user, playlist_id), _event(conn, new, "shares", user)


def remove_share(conn: Connection, user: User, playlist_id: int, target_user_id: int):
    row, _ = require_playlist(conn, user, playlist_id, "manage")
    before = _recipients(conn, row.id, row.owner_id, row.visibility)
    res = conn.execute(
        delete(playlist_shares).where(
            playlist_shares.c.playlist_id == playlist_id, playlist_shares.c.user_id == target_user_id
        )
    )
    if res.rowcount == 0:
        raise NotFound("share not found")
    new = _touch(conn, playlist_id, items_changed=False)
    # The removed user is told too, so their client can drop the playlist.
    return list_shares(conn, user, playlist_id), _event(conn, new, "shares", user, before)


def leave_share(conn: Connection, user: User, playlist_id: int) -> Event:
    """A user removes a playlist that was shared with them from their own list."""
    row = conn.execute(select(playlists).where(playlists.c.id == playlist_id)).first()
    if row is None or playlist_role(conn, user, row) not in ("editor", "viewer"):
        raise NotFound("playlist not found")
    before = _recipients(conn, row.id, row.owner_id, row.visibility)
    conn.execute(
        delete(playlist_shares).where(
            playlist_shares.c.playlist_id == playlist_id, playlist_shares.c.user_id == user.id
        )
    )
    new = _touch(conn, playlist_id, items_changed=False)
    return _event(conn, new, "shares", user, before)


# --- events --------------------------------------------------------------------------------


def events_since(conn: Connection, user_id: int, after_seq: int, limit: int = 500) -> list[Event]:
    rows = conn.execute(
        select(playlist_events).where(playlist_events.c.seq > after_seq).order_by(playlist_events.c.seq).limit(limit)
    ).all()
    out = []
    for r in rows:
        rec = json.loads(r.recipients_json)
        e = Event(r.seq, r.playlist_id, r.type, r.version, r.actor_id, rec)
        if e.visible_to(user_id):
            out.append(e)
    return out


def latest_event_seq(conn: Connection) -> int:
    return conn.execute(select(func.coalesce(func.max(playlist_events.c.seq), 0))).scalar_one()


def prune_events(conn: Connection) -> None:
    conn.execute(delete(playlist_events).where(playlist_events.c.at < now_ms() - _EVENT_RETENTION_MS))
