from audium.api.subsonic import envelope
from audium.api.subsonic.envelope import SubsonicError
from audium.api.subsonic.routing import Call, endpoint
from audium.jobs import queue as jobq
from audium.scanner.tasks import SCAN_QUEUE, enqueue_scan
from audium.services import catalog
from audium.services.users import find_by_username, user_from_row

EXTENSIONS = [
    {"name": "apiKeyAuthentication", "versions": [1]},
    {"name": "formPost", "versions": [1]},
    {"name": "transcodeOffset", "versions": [1]},
]


@endpoint("ping")
def ping(_call: Call) -> dict:
    return {}


@endpoint("getLicense")
def get_license(_call: Call) -> dict:
    return {"license": {"valid": True}}


@endpoint("getOpenSubsonicExtensions", auth=False)
def get_extensions(_call: Call) -> dict:
    # Without login, as OpenSubsonic requires: apps ask before they know how to authenticate.
    return {"openSubsonicExtensions": EXTENSIONS}


@endpoint("tokenInfo")
def token_info(call: Call) -> dict:
    return {"tokenInfo": {"username": call.user.username}}


@endpoint("getUser")
def get_user(call: Call) -> dict:
    """The caller's own account; admins may look up others (they manage accounts)."""
    name = (call.get("username") or call.user.username).strip().lower()
    user = call.user
    if name != user.username:
        if not user.is_admin:
            raise SubsonicError(envelope.NOT_AUTHORIZED, "you can only look up your own account")
        with call.db.read() as conn:
            row = find_by_username(conn, name)
        if row is None:
            raise SubsonicError(envelope.NOT_FOUND, "user not found")
        user = user_from_row(row)
    with call.db.read() as conn:
        folders = [r.id for r in catalog.music_folders(conn)]
    return {
        "user": {
            "username": user.username,
            "scrobblingEnabled": True,
            "adminRole": user.is_admin,
            "settingsRole": False,
            "downloadRole": True,
            "uploadRole": False,
            "playlistRole": True,
            "coverArtRole": False,
            "commentRole": False,
            "podcastRole": False,
            "streamRole": True,
            "jukeboxRole": False,
            "shareRole": False,
            "videoConversionRole": False,
            "folder": folders,
        }
    }


def _scan_status(call: Call) -> dict:
    with call.db.read() as conn:
        scanning = jobq.has_active(conn, SCAN_QUEUE, "scan")
        count = catalog.present_track_count(conn)
    return {"scanStatus": {"scanning": scanning, "count": count}}


@endpoint("getScanStatus")
def get_scan_status(call: Call) -> dict:
    return _scan_status(call)


@endpoint("startScan")
def start_scan(call: Call) -> dict:
    if not call.user.is_admin:
        raise SubsonicError(envelope.NOT_AUTHORIZED, "only admins can start a scan")
    with call.db.write() as conn:
        enqueue_scan(conn)
    return _scan_status(call)
