"""Why a track is in a station, as a short German text for the admin ("Warum?" column).

From the shares similarity.blend gives each track, e.g.
"Klingt ähnlich 70 % · Genre: Rock, 1994 30 %". Sources with a small share are left out.
"""

from sqlalchemy import Connection, select

from audium.analysis import explain
from audium.analysis.similarity import Blend
from audium.db.schema import artists, genres, track_features, track_genres, tracks

_MIN_PART = 0.2  # of the track's total score; smaller shares are not mentioned


def _genre_year(names: list[str], year: int | None) -> str:
    bits = [", ".join(names[:2]), str(year) if year else ""]
    text = ", ".join(b for b in bits if b)
    return f"Genre: {text}" if text else "Genre/Jahr"


def describe(conn: Connection, station: Blend, own: str = "Eigener Titel") -> dict[int, str]:
    """track id -> reason, for every track of the station. `own`: label of the group's own
    tracks ("Vom Album", "Vom Künstler")."""
    ids = [t for t, _ in station.picks]
    if not ids:
        return {}
    feats = {r.track_id: r for r in conn.execute(select(track_features).where(track_features.c.track_id.in_(ids)))}
    names: dict[int, list[str]] = {}
    for t, name in conn.execute(
        select(track_genres.c.track_id, genres.c.name)
        .join(genres, genres.c.id == track_genres.c.genre_id)
        .where(track_genres.c.track_id.in_(ids))
        .order_by(track_genres.c.track_id, genres.c.name)
    ):
        names.setdefault(t, []).append(name)
    info = {
        r.id: r
        for r in conn.execute(
            select(tracks.c.id, tracks.c.year, artists.c.name.label("artist"))
            .join(artists, artists.c.id == tracks.c.artist_id)
            .where(tracks.c.id.in_(ids))
        )
    }
    seed_names = dict(
        conn.execute(select(artists.c.id, artists.c.name).where(artists.c.id.in_(set(station.via.values())))).all()
    )

    def part(t: int, source: str) -> str:
        if source == "seed":
            return "Startpunkt"
        if source == "own":
            return own
        if source == "sound":
            return "Klingt ähnlich"
        if source == "features":
            text = explain.describe(feats[t]) if t in feats else ""
            return f"Ähnliche Merkmale ({text})" if text else "Ähnliche Merkmale"
        if source == "taste":
            return "Passt zu deinem Geschmack"
        if source == "artists":
            via = seed_names.get(station.via.get(t, -1))
            artist = info[t].artist if t in info else "diese Band"
            return f"Fans von {via} hören auch {artist}" if via else "Fans hören auch"
        text = _genre_year(names.get(t, []), info[t].year if t in info else None)
        return f"Ersatz, {text}" if source == "fallback" else text

    out: dict[int, str] = {}
    for t, why in station.picks:
        total = sum(why.values()) or 1.0
        ranked = sorted(why.items(), key=lambda kv: -kv[1])
        kept = [(s, v) for i, (s, v) in enumerate(ranked) if i == 0 or v / total >= _MIN_PART]
        if len(kept) == 1:
            out[t] = part(t, kept[0][0])
        else:
            out[t] = " · ".join(f"{part(t, s)} {round(100 * v / total)} %" for s, v in kept)
        if t in station.skipped:
            out[t] += f" · in ähnlichem Radio übersprungen (× {station.skipped[t]:.2f})".replace(".", ",")
    return out
