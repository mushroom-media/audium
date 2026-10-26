"""Features audium does not have. Listing them gives empty lists, so apps that ask on startup
keep working; everything else answers "not supported" (code 0) through the dispatcher."""

from audium.api.subsonic.routing import Call, endpoint

_EMPTY_LISTS = {
    "getPodcasts": "podcasts",
    "getNewestPodcasts": "newestPodcasts",
    "getInternetRadioStations": "internetRadioStations",
    "getShares": "shares",
    "getBookmarks": "bookmarks",
    "getVideos": "videos",
    "getChatMessages": "chatMessages",
}


def _register(name: str, key: str) -> None:
    @endpoint(name)
    def empty(_call: Call) -> dict:
        return {key: {}}


for _name, _key in _EMPTY_LISTS.items():
    _register(_name, _key)


@endpoint("getLyrics")
def get_lyrics(_call: Call) -> dict:
    return {"lyrics": {}}  # lyrics tags are not read yet (docs/subsonic.md, open questions)


@endpoint("getLyricsBySongId")
def get_lyrics_by_song_id(_call: Call) -> dict:
    return {"lyricsList": {}}
