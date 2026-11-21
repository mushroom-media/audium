"""Detected music styles -> genres.

Two levels:
- *genre*: the ~35 names of genres.py. Visible, used for navigation and genre auto-playlists.
- *style*: the 400 Discogs styles that Essentia's genre_discogs400 model predicts ("Deep House",
  "Boom Bap", "Shoegaze"). Kept per track for style auto-playlists and rules.

Every style maps to one genre (or none, e.g. spoken word) through the table below, maintained by
hand. Model labels look like "Electronic---Deep House": the part before "---" is Discogs' top
genre, which is far too coarse on its own ("Electronic" covers House, Techno and Ambient).

Genre tags in the files win: detected genres only fill tracks without any genre tag. A track's
detected genres are smoothed with its album (half track, half album average), so one odd track
does not get its own genre and an album does not spread over many.
"""

import functools
from collections import defaultdict

from sqlalchemy import Connection, delete, func, select, update

from audium.analysis import genres as genre_norm
from audium.db.schema import styles, track_genres, track_styles, tracks

# Discogs top genre -> (genre for its styles, {style: genre for the exceptions}).
_TABLE: dict[str, tuple[str | None, dict[str, str | None]]] = {
    "Blues": ("Blues", {"Rhythm & Blues": "R&B"}),
    "Brass & Military": (None, {}),
    "Children's": ("Children's", {}),
    "Classical": ("Classical", {}),
    "Electronic": (
        "Electronic",
        {
            **dict.fromkeys(
                ("Acid House", "Bassline", "Deep House", "Electro House", "Euro House", "Garage House",
                 "Ghetto House", "Hard House", "Hip-House", "House", "Italo House", "Progressive House",
                 "Speed Garage", "Tech House", "Tribal House", "Tropical House", "UK Garage"),
                "House",
            ),
            **dict.fromkeys(
                ("Acid", "Deep Techno", "Dub Techno", "Hard Techno", "Minimal", "Minimal Techno", "Schranz",
                 "Techno"),
                "Techno",
            ),
            **dict.fromkeys(
                ("Goa Trance", "Hands Up", "Hard Trance", "Progressive Trance", "Psy-Trance", "Tech Trance",
                 "Trance"),
                "Trance",
            ),
            **dict.fromkeys(("Drum n Bass", "Halftime", "Jungle"), "Drum & Bass"),
            "Dubstep": "Dubstep",
            **dict.fromkeys(
                ("Ambient", "Berlin-School", "Chillwave", "Dark Ambient", "Downtempo", "Drone", "Dungeon Synth",
                 "Illbient", "New Age"),
                "Ambient",
            ),
            **dict.fromkeys(("Disco", "Disco Polo", "Euro-Disco", "Hi NRG", "Italo-Disco", "Nu-Disco"), "Disco"),
            **dict.fromkeys(("Dance-pop", "Eurobeat", "Eurodance", "Italodance", "Synth-pop"), "Pop"),
            **dict.fromkeys(("Grime", "Hip Hop"), "Hip-Hop"),
            **dict.fromkeys(("Acid Jazz", "Future Jazz", "Jazzdance"), "Jazz"),
            "Modern Classical": "Classical",
            "Latin": "Latin",
            "Dub": "Reggae",
            "Neofolk": "Folk",
            **dict.fromkeys(("Darkwave", "New Wave"), "Alternative"),
        },
    ),
    "Folk, World, & Country": (
        "World",
        {
            **dict.fromkeys(("Bluegrass", "Cajun", "Country", "Hillbilly", "Honky Tonk"), "Country"),
            **dict.fromkeys(("Celtic", "Folk", "Nordic"), "Folk"),
            **dict.fromkeys(("Polka", "Volksmusik"), "Schlager"),
            "Gospel": "Gospel",
        },
    ),
    "Funk / Soul": (
        "Soul",
        {
            **dict.fromkeys(("Afrobeat", "Boogie", "Free Funk", "Funk", "P.Funk"), "Funk"),
            **dict.fromkeys(
                ("Contemporary R&B", "New Jack Swing", "Rhythm & Blues", "Swingbeat"),
                "R&B",
            ),
            "Disco": "Disco",
            "Gospel": "Gospel",
        },
    ),
    "Hip Hop": ("Hip-Hop", {"RnB/Swing": "R&B", "Trip Hop": "Electronic"}),
    "Jazz": ("Jazz", {"Bossa Nova": "Latin", "Afrobeat": "Funk"}),
    "Latin": ("Latin", {}),
    "Non-Music": (
        None,
        dict.fromkeys(
            ("Audiobook", "Dialogue", "Education", "Interview", "Monolog", "Poetry", "Radioplay", "Spoken Word"),
            "Audiobook",
        ),
    ),
    "Pop": ("Pop", {"Schlager": "Schlager", "Indie Pop": "Indie"}),
    "Reggae": ("Reggae", {}),
    "Rock": (
        "Rock",
        {
            **dict.fromkeys(
                ("Atmospheric Black Metal", "Black Metal", "Death Metal", "Deathcore", "Depressive Black Metal",
                 "Doom Metal", "Folk Metal", "Funeral Doom Metal", "Funk Metal", "Goregrind", "Gothic Metal",
                 "Grindcore", "Heavy Metal", "Melodic Death Metal", "Metalcore", "Noisecore", "Nu Metal",
                 "Pornogrind", "Post-Metal", "Power Metal", "Progressive Metal", "Sludge Metal", "Speed Metal",
                 "Technical Death Metal", "Thrash", "Viking Metal"),
                "Metal",
            ),
            **dict.fromkeys(("Glam", "Hard Rock", "Stoner Rock"), "Hard Rock"),
            **dict.fromkeys(
                ("Crust", "Emo", "Hardcore", "Melodic Hardcore", "Oi", "Pop Punk", "Post-Hardcore",
                 "Power Violence", "Psychobilly", "Punk"),
                "Punk",
            ),
            **dict.fromkeys(
                ("Brit Pop", "Dream Pop", "Indie Rock", "Lo-Fi", "Math Rock", "Post Rock", "Shoegaze"),
                "Indie",
            ),
            **dict.fromkeys(
                ("Alternative Rock", "Coldwave", "Deathrock", "Ethereal", "Goth Rock", "Grunge", "Industrial",
                 "New Wave", "No Wave", "Noise", "Post-Punk"),
                "Alternative",
            ),
            **dict.fromkeys(("Acoustic", "Folk Rock", "Neofolk"), "Folk"),
            **dict.fromkeys(("Pop Rock", "Power Pop", "Yé-Yé"), "Pop"),
            "Country Rock": "Country",
            "Doo Wop": "R&B",
            "Ska": "Reggae",
            "Lounge": "Jazz",
        },
    ),
    "Stage & Screen": ("Soundtrack", {}),
}  # fmt: skip

# A style "belongs" to a track from this probability on (model output, averaged over the track).
MIN_STYLE_PROB = 0.3
# Stored per track: the strongest styles above KEEP_STYLE_PROB, at most KEEP_STYLES.
KEEP_STYLES = 5
KEEP_STYLE_PROB = 0.05
# Detected genres per track: share of the (track + album) genre distribution, at most MAX_GENRES.
MIN_GENRE_SHARE = 0.25
MAX_GENRES = 3


def split_label(label: str) -> tuple[str, str]:
    """ "Electronic---Deep House" -> ("Electronic", "Deep House")."""
    parent, _, name = label.partition("---")
    return (parent, name) if name else ("", parent)


def genre_of(label: str) -> str | None:
    parent, name = split_label(label)
    default, exceptions = _TABLE.get(parent, (None, {}))
    return exceptions.get(name, default)


# Style names that mean different things in different Discogs genres or in tags ("Lo-Fi" is a
# rock style there, but in tags mostly lo-fi hip-hop): no genre by name.
_AMBIGUOUS_NAMES = {"lofi", "hardcore", "industrial", "acoustic"}


@functools.cache
def _genre_by_style_name() -> dict[str, str]:
    out: dict[str, str] = {}
    for parent, (default, exceptions) in _TABLE.items():
        if default:
            out[genre_norm.fold(parent)] = default
        for name, genre in exceptions.items():
            if genre:
                out[genre_norm.fold(name)] = genre
    for name in _AMBIGUOUS_NAMES:
        out.pop(name, None)
    return out


def genre_of_style(name: str) -> str | None:
    """The genre a style name ("Shoegaze", "Neofolk") counts for, also when it comes from a tag."""
    return _genre_by_style_name().get(genre_norm.fold(name))


def top_styles(labels: list[str], probs) -> list[tuple[str, float]]:
    """The strongest styles of one track, strongest first."""
    order = sorted(range(len(labels)), key=lambda i: -float(probs[i]))[:KEEP_STYLES]
    return [(labels[i], round(float(probs[i]), 4)) for i in order if float(probs[i]) >= KEEP_STYLE_PROB]


def style_ids(conn: Connection, labels: set[str], cache: dict[str, int]) -> dict[str, int]:
    """Ids of style labels, created on first use. Names that occur under several Discogs genres
    ("Hardcore" in Rock and in Electronic) get the genre in brackets."""
    missing = [lab for lab in labels if lab not in cache]
    if missing:
        for row in conn.execute(select(styles.c.id, styles.c.label).where(styles.c.label.in_(missing))):
            cache[row.label] = row.id
    for label in sorted(lab for lab in labels if lab not in cache):
        parent, name = split_label(label)
        taken = conn.execute(select(styles.c.id).where(styles.c.name == name)).first()
        shown = f"{name} ({parent})" if taken else name
        cache[label] = conn.execute(
            styles.insert().values(
                label=label, name=shown, parent=parent, genre=genre_of(label), slug=genre_norm.slug(label)
            )
        ).inserted_primary_key[0]
    return {lab: cache[lab] for lab in labels}


def refresh_detected_genres(conn: Connection, genre_id) -> int:
    """Recompute the detected genres of all tracks without genre tags. `genre_id(name)` returns the
    id of a genre, creating it if needed. Returns the number of tracks with detected genres."""
    rows = conn.execute(
        select(track_styles.c.track_id, tracks.c.album_id, styles.c.genre, track_styles.c.prob)
        .join(tracks, tracks.c.id == track_styles.c.track_id)
        .join(styles, styles.c.id == track_styles.c.style_id)
        .where(tracks.c.missing_since.is_(None), styles.c.genre.is_not(None))
    ).all()
    per_track: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    album_of: dict[int, int] = {}
    for track_id, album_id, genre, prob in rows:
        per_track[track_id][genre] += prob
        album_of[track_id] = album_id
    shares = {t: _normalized(g) for t, g in per_track.items()}
    per_album: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    album_size: dict[int, int] = defaultdict(int)
    for t, dist in shares.items():
        album_size[album_of[t]] += 1
        for genre, share in dist.items():
            per_album[album_of[t]][genre] += share
    tagged = set(
        conn.execute(select(track_genres.c.track_id).where(track_genres.c.source == "tag").distinct()).scalars()
    )
    conn.execute(delete(track_genres).where(track_genres.c.source == "detected"))
    out = []
    for t, dist in shares.items():
        if t in tagged:
            continue
        album, n = per_album[album_of[t]], album_size[album_of[t]]
        mixed = {g: 0.5 * dist.get(g, 0.0) + 0.5 * album[g] / n for g in set(dist) | set(album)}
        ranked = sorted(mixed.items(), key=lambda kv: -kv[1])
        chosen = [kv for kv in ranked[:MAX_GENRES] if kv[1] >= MIN_GENRE_SHARE] or ranked[:1]
        total = sum(share for _g, share in chosen)
        out.extend(
            {"track_id": t, "genre_id": genre_id(g), "source": "detected", "weight": round(share / total, 3)}
            for g, share in chosen
        )
    for i in range(0, len(out), 5000):
        conn.execute(track_genres.insert(), out[i : i + 5000])
    return len({r["track_id"] for r in out})


def refresh_style_counts(conn: Connection) -> None:
    """Visible tracks per style (with at least MIN_STYLE_PROB)."""
    counted = (
        select(func.count())
        .select_from(track_styles.join(tracks, tracks.c.id == track_styles.c.track_id))
        .where(
            track_styles.c.style_id == styles.c.id,
            track_styles.c.prob >= MIN_STYLE_PROB,
            tracks.c.missing_since.is_(None),
        )
        .scalar_subquery()
    )
    conn.execute(update(styles).values(track_count=counted))


def _normalized(dist: dict[str, float]) -> dict[str, float]:
    total = sum(dist.values())
    return {g: v / total for g, v in dist.items()} if total else {}
