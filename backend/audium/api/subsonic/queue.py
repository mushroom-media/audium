from audium.api.subsonic import ids, mapping
from audium.api.subsonic.routing import Call, endpoint
from audium.services import playqueue


@endpoint("savePlayQueue")
def save_play_queue(call: Call) -> dict:
    """Without any id the saved queue is cleared."""
    track_ids = [ids.parse_one(v, ids.TRACK) for v in call.getall("id")]
    current = call.get("current")
    with call.db.write() as conn:
        playqueue.save(
            conn,
            call.user.id,
            track_ids,
            ids.parse_one(current, ids.TRACK) if current else None,
            call.int("position", 0, 0) or 0,
            call.client,
        )
    return {}


@endpoint("getPlayQueue")
def get_play_queue(call: Call) -> dict:
    with call.db.read() as conn:
        saved = playqueue.load(conn, call.user.id)
        if saved is None:
            return {}
        entries = mapping.songs(conn, call.user, saved["track_ids"])
    queue = {
        "current": ids.make(ids.TRACK, saved["current"]) if saved["current"] else None,
        "position": saved["position_ms"],
        "username": call.user.username,
        "changed": mapping.iso(saved["updated_at"]),
        "changedBy": saved["changed_by"] or "",
        "entry": entries,
    }
    return {"playQueue": {k: v for k, v in queue.items() if v is not None}}
