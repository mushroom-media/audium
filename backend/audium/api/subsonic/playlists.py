"""Playlists: the user's own, shared and public ones (pl-) and the published auto-playlists (ap-).

Rights are the web API's (services/permissions.py): viewers read, editors change tracks, only
the owner renames or deletes; a playlist one may not see is "not found". Smart playlists fill
themselves and auto-playlists belong to audium, so their tracks cannot be changed here (50).
Every change goes through services/playlists.py and reaches open web UIs as a live update.
"""

from audium.api.subsonic import ids, mapping
from audium.api.subsonic.envelope import NOT_AUTHORIZED, SubsonicError
from audium.api.subsonic.routing import Call, endpoint
from audium.services import auto as auto_service
from audium.services import playlists as svc
from audium.services.permissions import require_playlist

_READONLY = "this playlist fills itself and cannot be changed by hand"


def _track_ids(values: list[str]) -> list[int]:
    return [ids.parse_one(v, ids.TRACK) for v in values]


def _publish(call: Call, events: list) -> None:
    call.state.bus.publish(*events)


@endpoint("getPlaylists")
def get_playlists(call: Call) -> dict:
    username = call.get("username")
    if username and username.strip().lower() != call.user.username:
        raise SubsonicError(NOT_AUTHORIZED, "you can only list your own playlists")
    with call.db.read() as conn:
        own = [mapping.playlist(p) for p in svc.list_playlists(conn, call.user, "all", 1000, 0)]
        autos = [mapping.auto_playlist(a) for a in auto_service.list_auto(conn, call.user, "published")]
    return {"playlists": {"playlist": own + autos}}


def _playlist_with_entries(call: Call, conn, raw_id: str) -> dict:
    kind, item_id = ids.parse(raw_id, ids.PLAYLIST, ids.AUTO)
    if kind == ids.AUTO:
        info = mapping.auto_playlist(auto_service.get_auto(conn, call.user, item_id))
        track_ids = auto_service.track_ids(conn, call.user, item_id)
    else:
        pl = svc.get_playlist(conn, call.user, item_id)
        shares = [s["user"]["username"] for s in svc.list_shares(conn, call.user, item_id)]
        info = mapping.playlist(pl, shares)
        track_ids = [t for _item, t in svc.available_items(conn, call.user, item_id)]
    entries = mapping.songs(conn, call.user, track_ids)
    # songCount/duration of the list as delivered (files that are gone are left out)
    info.update(entry=entries, songCount=len(entries), duration=sum(e.get("duration", 0) for e in entries))
    return info


@endpoint("getPlaylist")
def get_playlist(call: Call) -> dict:
    with call.db.read() as conn:
        return {"playlist": _playlist_with_entries(call, conn, call.require("id"))}


@endpoint("createPlaylist")
def create_playlist(call: Call) -> dict:
    """With `name`: a new playlist. With `playlistId`: replace that playlist's tracks."""
    track_ids = _track_ids(call.getall("songId"))
    target = call.get("playlistId")
    events = []
    with call.db.write() as conn:
        if target:
            kind, playlist_id = ids.parse(target, ids.PLAYLIST, ids.AUTO)
            if kind == ids.AUTO:
                raise SubsonicError(NOT_AUTHORIZED, _READONLY)
            row, _role = require_playlist(conn, call.user, playlist_id, "edit")
            if row.kind == "smart":
                raise SubsonicError(NOT_AUTHORIZED, _READONLY)
            old = svc.all_item_ids(conn, playlist_id)
            if old:
                events.append(svc.remove_items(conn, call.user, playlist_id, old)[1])
            for i in range(0, len(track_ids), svc.MAX_ADD):
                chunk = track_ids[i : i + svc.MAX_ADD]
                events.append(svc.add_items(conn, call.user, playlist_id, chunk)[2])
            raw_id = ids.make(ids.PLAYLIST, playlist_id)
        else:
            out, event = svc.create_playlist(conn, call.user, call.require("name"), None, "private", track_ids)
            events.append(event)
            raw_id = ids.make(ids.PLAYLIST, out["id"])
        result = _playlist_with_entries(call, conn, raw_id)
    _publish(call, events)
    return {"playlist": result}


@endpoint("updatePlaylist")
def update_playlist(call: Call) -> dict:
    kind, playlist_id = ids.parse(call.require("playlistId"), ids.PLAYLIST, ids.AUTO)
    if kind == ids.AUTO:
        raise SubsonicError(NOT_AUTHORIZED, _READONLY)
    name, comment, public = call.get("name"), call.get("comment"), call.get("public")
    to_add = _track_ids(call.getall("songIdToAdd"))
    to_remove = sorted({int(v) for v in call.getall("songIndexToRemove") if v.strip().isdigit()})
    events = []
    with call.db.write() as conn:
        # Apps often resend unchanged values; only real changes need the owner's rights.
        current = svc.get_playlist(conn, call.user, playlist_id)
        visibility = None if public is None else ("users" if call.bool("public") else "private")
        new_comment = comment.strip() or None if comment is not None else None
        changes = {
            "name": name if name is not None and name.strip() != current["name"] else None,
            "description": comment if comment is not None and new_comment != current["description"] else None,
            "visibility": visibility if visibility != current["visibility"] else None,
        }
        if any(v is not None for v in changes.values()):
            events.append(svc.update_playlist(conn, call.user, playlist_id, **changes)[1])
        if to_add or to_remove:
            row, _role = require_playlist(conn, call.user, playlist_id, "edit")
            if row.kind == "smart":
                raise SubsonicError(NOT_AUTHORIZED, _READONLY)
            if to_remove:
                # Indexes refer to the list getPlaylist returned (playable tracks only).
                items = svc.available_items(conn, call.user, playlist_id)
                item_ids = [items[i][0] for i in to_remove if i < len(items)]
                if item_ids:
                    events.append(svc.remove_items(conn, call.user, playlist_id, item_ids)[1])
            for i in range(0, len(to_add), svc.MAX_ADD):
                events.append(svc.add_items(conn, call.user, playlist_id, to_add[i : i + svc.MAX_ADD])[2])
    _publish(call, events)
    return {}


@endpoint("deletePlaylist")
def delete_playlist(call: Call) -> dict:
    kind, playlist_id = ids.parse(call.require("id"), ids.PLAYLIST, ids.AUTO)
    if kind == ids.AUTO:
        raise SubsonicError(NOT_AUTHORIZED, "auto-playlists belong to audium")
    with call.db.write() as conn:
        event = svc.delete_playlist(conn, call.user, playlist_id)
    _publish(call, [event])
    return {}
