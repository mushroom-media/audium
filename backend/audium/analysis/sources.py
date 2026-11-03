"""Where radio stations and mixes take their tracks from (Einstellungen > Radio & Mixe, admin).

Server-wide, stored in app_state as JSON. Each source has a switch and a weight (1-100):
- sound:    sound fingerprints (Discogs-EffNet), "klingt ähnlich"
- features: the hand-made descriptors (BPM, energy, danceability, moods ...)
- genre:    shared genres and a similar year
- artists:  artists whose fans listen to the seed's artist (ListenBrainz, services/similar_artists.py);
            off by default because it sends artist names/MusicBrainz ids to ListenBrainz
- taste:    per listener, of the tracks the others found the ones they like (favourites, plays)
            rank higher (analysis/taste.py); it never brings in tracks of its own

A station ranks its candidates per source and adds the ranks up by weight (similarity.blend).
Tracks the listener skipped early in a similar station rank lower whatever the switches say
(analysis/taste.py). The switches also decide which mixes the auto-playlists make: sound off means no sound mixes,
features off no mixes over the descriptors. At least one source stays on.
"""

import json
from dataclasses import dataclass

from sqlalchemy import Connection

from audium.db.state import get_state, set_state
from audium.errors import BadRequest

STATE = "radio.sources"
SOURCES = ("sound", "features", "genre", "artists", "taste")
MIN_WEIGHT = 1
MAX_WEIGHT = 100
# Like before the switches existed: fingerprints first, descriptors and genres to round it off.
DEFAULTS = {
    "sound": (True, 100),
    "features": (True, 30),
    "genre": (True, 20),
    "artists": (False, 50),
    "taste": (True, 30),
}


@dataclass(frozen=True)
class Source:
    on: bool
    weight: int


def load(conn: Connection) -> dict[str, Source]:
    try:
        stored = json.loads(get_state(conn, STATE) or "{}")
    except ValueError:
        stored = {}
    out: dict[str, Source] = {}
    for name in SOURCES:
        on, weight = DEFAULTS[name]
        value = stored.get(name) if isinstance(stored, dict) else None
        if isinstance(value, dict):
            on = bool(value.get("on", on))
            w = value.get("weight", weight)
            weight = min(MAX_WEIGHT, max(MIN_WEIGHT, int(w))) if isinstance(w, int | float) else weight
        out[name] = Source(on, weight)
    return out


def save(conn: Connection, changes: dict[str, dict]) -> tuple[dict[str, Source], set[str]]:
    """The sources after `changes` ({name: {on?, weight?}}) and the names whose switch changed."""
    before = load(conn)
    after = dict(before)
    for name, change in changes.items():
        if name not in SOURCES:
            raise BadRequest(f"unknown source {name!r}")
        weight = change.get("weight", before[name].weight)
        if not isinstance(weight, int) or not MIN_WEIGHT <= weight <= MAX_WEIGHT:
            raise BadRequest(f"weight must be {MIN_WEIGHT}-{MAX_WEIGHT}")
        after[name] = Source(bool(change.get("on", before[name].on)), weight)
    if not any(s.on for s in after.values()):
        raise BadRequest("at least one source must stay on")
    set_state(conn, STATE, json.dumps({n: {"on": s.on, "weight": s.weight} for n, s in after.items()}))
    return after, {n for n in SOURCES if before[n].on != after[n].on}


# Further station options, next to the sources (same page).
OPTIONS_STATE = "radio.options"
# smooth_tempo: order a station so the tempo does not jump much (similarity.smooth_tempo).
OPTION_DEFAULTS = {"smooth_tempo": True}


def options(conn: Connection) -> dict[str, bool]:
    try:
        stored = json.loads(get_state(conn, OPTIONS_STATE) or "{}")
    except ValueError:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {k: bool(stored.get(k, d)) for k, d in OPTION_DEFAULTS.items()}


def save_options(conn: Connection, changes: dict[str, bool]) -> dict[str, bool]:
    unknown = set(changes) - set(OPTION_DEFAULTS)
    if unknown:
        raise BadRequest(f"unknown option {sorted(unknown)[0]!r}")
    after = options(conn) | {k: bool(v) for k, v in changes.items()}
    set_state(conn, OPTIONS_STATE, json.dumps(after))
    return after


def weights(cfg: dict[str, Source]) -> dict[str, float]:
    """The switched-on sources and their share (summing to 1)."""
    on = {n: float(s.weight) for n, s in cfg.items() if s.on}
    total = sum(on.values()) or 1.0
    return {n: w / total for n, w in on.items()}
