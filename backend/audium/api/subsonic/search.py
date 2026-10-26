"""search3 (and the folder-style search2) over the full-text index.

An empty query (also `""`, as some apps send it) lists everything in a stable order: apps
such as Symfonium sync the whole library this way, page by page via the *Offset parameters.
"""

from audium.api.subsonic import ids, mapping
from audium.api.subsonic.routing import Call, endpoint
from audium.db import search
from audium.services import catalog

MAX_COUNT = 1000


def _search(call: Call, as_dir: bool) -> dict:
    query = (call.get("query") or "").strip().strip('"').strip()
    root_id = ids.folder(call.get("musicFolderId"))
    wanted = {
        kind: (call.int(f"{kind}Count", 20, 0, MAX_COUNT), call.int(f"{kind}Offset", 0, 0))
        for kind in ("artist", "album", "song")
    }
    found: dict[str, list[int]] = {}
    with call.db.read() as conn:
        match = search.build_match_query(query) if query else None
        for kind, (count, offset) in wanted.items():
            internal = "track" if kind == "song" else kind
            if count == 0:
                found[kind] = []
            elif not query:
                found[kind] = catalog.all_ids(conn, internal, count, offset, root_id)
            elif match is None:
                found[kind] = []  # too short to search for
            else:
                found[kind] = search.search_ids(conn, internal, match, count, offset)
        return {
            "artist": mapping.artists(conn, call.user, found["artist"]),
            "album": mapping.albums(conn, call.user, found["album"], as_dir=as_dir),
            "song": mapping.songs(conn, call.user, found["song"]),
        }


@endpoint("search3")
def search3(call: Call) -> dict:
    return {"searchResult3": _search(call, as_dir=False)}


@endpoint("search2")
def search2(call: Call) -> dict:
    return {"searchResult2": _search(call, as_dir=True)}
