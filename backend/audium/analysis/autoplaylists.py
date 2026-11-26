"""Generates auto-playlist suggestions and re-evaluates smart playlists.

Kinds (`generator`):
- family:  per broad genre ("Rock" = Rock, Alternative, Punk, ...; see genres.family), the
           genre tiles of the Discover page
- tag:     per genre, per decade, the biggest genre x decade combinations ("Rock der 90er") and
           per detected style with enough tracks ("Deep House")
- rule:    built-in rules over audio features ("Workout", "Zum Entspannen", ...)
- cluster: k-means "mixes" over the feature vectors, named after their dominant traits
- sound:   k-means "mixes" over the sound fingerprints, named after their most common styles
- custom:  rule playlists the admin created; only re-evaluated here

The admin picks the source (state key SOURCE_STATE): "all" makes tag, rule, style and cluster
playlists; "sound" only what the sound recognition found (detected styles and sound mixes).

Names and descriptions are written in German and English (name/name_en; audium/i18n.py), so every
user sees them in their language. Item reasons ("128 BPM · hohe Energie") follow the server language.

New playlists start as "suggested" (only the admin sees them) until the admin publishes them;
genre and family playlists are published at once (Discover lists them under "Alle Genres").
Existing ones keep status, access and an admin-given name; only their tracks are refreshed.
A "dismissed" playlist is never recreated.
"""

import json
import math
import random
import zlib
from collections import Counter

import numpy as np
from sqlalchemy import Connection, delete, func, insert, select, update

from audium.analysis import explain, genre_covers, rules, sources
from audium.analysis import genres as genre_norm
from audium.analysis.similarity import embedding_matrix, feature_matrix
from audium.analysis.styles import MIN_STYLE_PROB
from audium.db.engine import Database
from audium.db.schema import (
    auto_playlist_items,
    auto_playlists,
    covers,
    genres,
    playlist_items,
    playlists,
    styles,
    track_features,
    track_genres,
    track_styles,
    tracks,
)
from audium.db.state import get_state
from audium.i18n import server_language, tr
from audium.logging import get_logger
from audium.scanner.covers import CoverStore
from audium.util import now_ms

log = get_logger(__name__)

MAX_ITEMS = 300
STORE_BATCH = 20  # playlists per write transaction in generate_in
MIN_GENRE_TRACKS = 30
MIN_DECADE_TRACKS = 30
MIN_COMBO_TRACKS = 25
MAX_COMBOS = 12
MIN_STYLE_TRACKS = 25
MAX_STYLES = 30
MIN_ANALYZED_FOR_RULES = 50
MIN_ANALYZED_FOR_CLUSTERS = 200
MIN_RULE_TRACKS = 15
MIX_SIZE = 200
SOURCE_STATE = "autoplaylists.source"
SOURCES = ("all", "sound")  # the first one is the default
# A genre gets a playlist of its own only with variety: at least `min_artists` artists, and the
# biggest one has at most `max_artist_share` of its tracks. Otherwise its tracks count for its
# parent genre ("Krautrock" -> "Rock"). The admin can change both (Einstellungen > Auto-Playlists).
GENRE_RULES_STATE = "autoplaylists.genre_rules"
GENRE_RULES_DEFAULT = {"min_artists": 5, "max_artist_share": 0.4}
MIN_ARTISTS_CHOICES = (1, 3, 5, 8, 12)
MAX_SHARE_CHOICES = (0.3, 0.4, 0.5, 1.0)  # 1.0 = no limit
# In genre and family playlists one artist fills at most this share (but always a few tracks).
ARTIST_CAP_SHARE = 0.1
MIN_ARTIST_CAP = 5

# Built-in rule playlists: key -> (name, description, rule, explain fields)
BUILTIN_RULES: dict[str, tuple[str, str, dict, tuple[str, ...]]] = {
    "workout": (
        "Workout", "Schnell und energiegeladen.",
        {"match": "all", "conditions": [
            {"field": "bpm", "op": "between", "value": [118, 160]},
            {"field": "energy", "op": ">=", "value": 0.65},
        ]},
        ("bpm", "energy"),
    ),
    "chill": (
        # Energy alone: it already counts notes and beat, and calm music often has no steady
        # beat at all (no BPM), which a tempo condition would leave out.
        "Zum Entspannen", "Ruhig und langsam.",
        {"match": "all", "conditions": [
            {"field": "energy", "op": "<=", "value": 0.4},
        ]},
        ("energy", "bpm"),
    ),
    "party": (
        "Party", "Tanzbar mit Druck.",
        {"match": "all", "conditions": [
            {"field": "danceability", "op": ">=", "value": 0.6},
            {"field": "energy", "op": ">=", "value": 0.55},
            {"field": "bpm", "op": "between", "value": [100, 135]},
        ]},
        ("bpm", "danceability", "energy"),
    ),
    "focus": (
        "Konzentration", "Gleichmäßig, nicht zu laut, warmer Klang.",
        {"match": "all", "conditions": [
            {"field": "energy", "op": "<=", "value": 0.55},
            {"field": "dynamics", "op": "<=", "value": 0.4},
            {"field": "brightness", "op": "<=", "value": 0.5},
        ]},
        ("energy", "dynamics", "brightness"),
    ),
    "good-mood": (
        "Gute Laune", "Dur, flott und lebendig.",
        {"match": "all", "conditions": [
            {"field": "mode", "op": "is", "value": "major"},
            {"field": "bpm", "op": ">=", "value": 110},
            {"field": "energy", "op": ">=", "value": 0.5},
        ]},
        ("key", "bpm", "energy"),
    ),
    "happy": ("Fröhlich", "", {"match": "all", "conditions": [{"field": "mood_happy", "op": ">=", "value": 0.6}]},
              ("mood_happy", "bpm")),
    "sad": ("Melancholisch", "", {"match": "all", "conditions": [{"field": "mood_sad", "op": ">=", "value": 0.6}]},
            ("mood_sad", "key")),
    "aggressive": ("Kraftvoll", "", {"match": "all", "conditions": [
        {"field": "mood_aggressive", "op": ">=", "value": 0.6}]}, ("mood_aggressive", "energy")),
    "relaxed": ("Entspannt", "", {"match": "all", "conditions": [
        {"field": "mood_relaxed", "op": ">=", "value": 0.6}]}, ("mood_relaxed", "bpm")),
}  # fmt: skip

# Cluster naming: column -> (word when clearly above average, word when clearly below)
_TRAIT_WORDS = {
    "bpm": ("schnell", "langsam"),
    "energy": ("energiegeladen", "ruhig"),
    "danceability": ("tanzbar", None),
    "brightness": ("hell", "warm"),
    "dynamics": ("dynamisch", "gleichmäßig"),
    "mode": ("in Dur", "in Moll"),
    "mood_happy": ("fröhlich", None),
    "mood_sad": ("melancholisch", None),
    "mood_aggressive": ("kraftvoll", None),
    "mood_relaxed": ("entspannt", None),
}


def source(conn: Connection) -> str:
    value = get_state(conn, SOURCE_STATE)
    return value if value in SOURCES else SOURCES[0]


def genre_rules(conn: Connection) -> dict:
    """{"min_artists": int, "max_artist_share": float}; values outside the choices fall back."""
    try:
        stored = json.loads(get_state(conn, GENRE_RULES_STATE) or "{}")
    except ValueError:
        stored = {}
    out = dict(GENRE_RULES_DEFAULT)
    if stored.get("min_artists") in MIN_ARTISTS_CHOICES:
        out["min_artists"] = stored["min_artists"]
    if stored.get("max_artist_share") in MAX_SHARE_CHOICES:
        out["max_artist_share"] = float(stored["max_artist_share"])
    return out


def seed_of(key: str) -> int:
    return zlib.crc32(key.encode())


def _short(decade: int) -> str:
    return str(decade)[2:] if decade < 2000 else str(decade)


def _both(de: str, **params) -> tuple[str, str]:
    """`de` in German and in English."""
    return tr("de", de, **params), tr("en", de, **params)


# --- helpers -------------------------------------------------------------------------------


def _present():
    return tracks.c.missing_since.is_(None)


def _shuffled(stmt, key: str):
    return stmt.order_by(rules.shuffle_key(seed_of(key))).limit(MAX_ITEMS)


def _with_reasons(conn: Connection, ids: list[int], fields: tuple[str, ...] | None, fixed: str | None = None):
    lang = server_language(conn)
    if fields is None:
        return [(t, fixed) for t in ids]
    rows = (
        {r.track_id: r for r in conn.execute(select(track_features).where(track_features.c.track_id.in_(ids)))}
        if ids
        else {}
    )
    return [(t, explain.describe(rows[t], fields, lang) if t in rows else fixed) for t in ids]


def _artist_cap(total: int) -> int:
    return max(MIN_ARTIST_CAP, math.ceil(ARTIST_CAP_SHARE * min(total, MAX_ITEMS)))


def _capped(rows, total: int) -> list[tuple[int, str]]:
    """(track, artist, reason) rows in playing order -> up to MAX_ITEMS (track, reason), each
    artist at most _artist_cap(total) times and each track once."""
    cap = _artist_cap(total)
    per_artist: Counter[int] = Counter()
    picked: dict[int, str] = {}
    for track_id, artist_id, reason in rows:
        if track_id in picked or per_artist[artist_id] >= cap:
            continue
        per_artist[artist_id] += 1
        picked[track_id] = reason
        if len(picked) >= MAX_ITEMS:
            break
    return list(picked.items())


def _varied(artists: list[int], rules_: dict, min_tracks: int) -> bool:
    """Enough tracks (one artist id per track) from enough artists, none dominating."""
    if len(artists) < min_tracks:
        return False
    counts = Counter(artists)
    return len(counts) >= rules_["min_artists"] and counts.most_common(1)[0][1] <= rules_["max_artist_share"] * len(
        artists
    )


def _genre_groups(conn: Connection, rules_: dict) -> list[dict]:
    """The genre playlists: genres with enough variety, each with the too-small genres below it
    folded in (deepest first: "Shoegaze" -> "Indie" -> "Rock"). A group is named after its genre,
    which need not be a tag of its own. Returns, biggest first, {"name", "tracks": {track: (artist,
    year, genre name)}, "names": genre names in it, own first}."""
    by_genre: dict[str, dict[int, tuple[int, int, str]]] = {}
    for track_id, artist_id, year, name in conn.execute(
        select(tracks.c.id, tracks.c.artist_id, tracks.c.year, genres.c.name)
        .join(track_genres, track_genres.c.track_id == tracks.c.id)
        .join(genres, genres.c.id == track_genres.c.genre_id)
        .where(_present())
    ):
        by_genre.setdefault(name, {})[track_id] = (artist_id, year, name)
    groups = {name: dict(members) for name, members in by_genre.items()}
    names = {name: [name] for name in groups}

    def ok(name: str) -> bool:
        return _varied([a for a, _, _ in groups[name].values()], rules_, MIN_GENRE_TRACKS)

    def depth(name: str, seen: frozenset = frozenset()) -> int:
        up = genre_norm.parent(name)
        return 0 if up is None or up in seen else 1 + depth(up, seen | {name})

    by_depth: dict[int, list[str]] = {}
    for name in groups:
        by_depth.setdefault(depth(name), []).append(name)
    for d in range(max(by_depth, default=0), -1, -1):  # a parent joins the next level up
        for name in sorted(by_depth.get(d, [])):
            if name not in groups or ok(name):
                continue
            up = genre_norm.parent(name)
            if up is None:
                continue
            if up not in groups:
                groups[up], names[up] = {}, [up]
                by_depth.setdefault(d - 1, []).append(up)
            for track_id, member in groups.pop(name).items():
                groups[up].setdefault(track_id, member)  # a track keeps its first genre as reason
            names[up] += names.pop(name)
    out = [{"name": n, "tracks": groups[n], "names": names[n]} for n in groups if ok(n)]
    out.sort(key=lambda g: -len(g["tracks"]))
    return out


def _family_specs(conn: Connection, detected_only: bool) -> list[dict]:
    """One playlist per broad genre with enough tracks; each track's reason is its own genre.
    `detected_only`: only genres the sound recognition found (source "sound")."""
    members: dict[str, dict[int, str]] = {}
    for g in conn.execute(select(genres.c.id, genres.c.name)):
        fam = genre_norm.family(g.name)
        if fam:
            members.setdefault(fam, {})[g.id] = g.name
    specs = []
    for fam in genre_norm.FAMILIES:
        ids = members.get(fam)
        if not ids:
            continue
        key = f"family:{genre_norm.slug(fam)}"
        where = [track_genres.c.genre_id.in_(list(ids)), _present()]
        if detected_only:
            where.append(track_genres.c.source == "detected")
        base = select(tracks.c.id, tracks.c.artist_id, track_genres.c.genre_id).join(
            track_genres, track_genres.c.track_id == tracks.c.id
        )
        total = conn.execute(
            select(func.count(func.distinct(tracks.c.id)))
            .select_from(tracks.join(track_genres, track_genres.c.track_id == tracks.c.id))
            .where(*where)
        ).scalar_one()
        if total < MIN_GENRE_TRACKS:
            continue
        # A track with two genres of the family counts once; no artist takes over the family.
        rows = conn.execute(base.where(*where).order_by(rules.shuffle_key(seed_of(key))))
        items = _capped(((t, a, ids[g]) for t, a, g in rows), total)
        if len(items) < MIN_GENRE_TRACKS:  # mostly one or two artists: not much of a broad genre
            continue
        names = sorted(set(ids.values()), key=lambda n: (n != fam, n))
        listed = ", ".join(names[:5])
        description, description_en = (
            _both("{names} und mehr.", names=listed) if len(names) > 5 else (f"{listed}.",) * 2
        )
        specs.append(
            {
                "key": key,
                "generator": "sound" if detected_only else "family",
                "name": fam,
                "name_en": tr("en", fam),
                "description": description,
                "description_en": description_en,
                "items": items,
                "status": "published",
            }
        )
    return specs


def _shuffled_members(members: dict[int, tuple], key: str) -> list[int]:
    order = sorted(members)
    random.Random(seed_of(key)).shuffle(order)
    return order


def _tag_specs(conn: Connection) -> list[dict]:
    specs = []
    rules_ = genre_rules(conn)
    groups = _genre_groups(conn, rules_)
    for g in groups:
        key = f"genre:{genre_norm.slug(g['name'])}"
        members = g["tracks"]
        order = _shuffled_members(members, key)
        items = _capped(((t, members[t][0], members[t][2]) for t in order), len(members))
        others = [n for n in g["names"] if n != g["name"]]
        if others:
            listed = ", ".join(sorted(others, key=lambda n: -sum(1 for m in members.values() if m[2] == n))[:4])
            description, description_en = _both("{name}, dazu {names}.", name=g["name"], names=listed)
        else:
            description, description_en = _both("Alles aus dem Genre {name}.", name=g["name"])
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": g["name"],
                "name_en": tr("en", g["name"]),
                "description": description,
                "description_en": description_en,
                "items": items,
                "status": "published",
            }
        )

    specs += _style_specs(conn, {g["name"] for g in groups})

    decade = (tracks.c.year // 10) * 10
    decade_rows = conn.execute(
        select(decade.label("d"), func.count())
        .where(_present(), tracks.c.year >= 1900)
        .group_by(decade)
        .having(func.count() >= MIN_DECADE_TRACKS)
    ).all()
    for d, _n in decade_rows:
        key = f"decade:{d}"
        stmt = select(tracks.c.id, tracks.c.year).where(_present(), tracks.c.year.between(d, d + 9))
        rows = conn.execute(stmt.order_by(rules.shuffle_key(seed_of(key))).limit(MAX_ITEMS)).all()
        name, name_en = _both("Die {d}er", d=_short(d))
        description, description_en = _both("Musik aus den Jahren {start} bis {end}.", start=d, end=d + 9)
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": name,
                "name_en": name_en,
                "description": description,
                "description_en": description_en,
                "items": [(r.id, str(r.year)) for r in rows],
            }
        )

    # Genre x decade over the same genre groups, with the same variety rule.
    combos = []
    for g in groups:
        per_decade: dict[int, dict[int, tuple]] = {}
        for track_id, member in g["tracks"].items():
            if member[1] >= 1900:
                per_decade.setdefault(member[1] // 10 * 10, {})[track_id] = member
        for d, members in per_decade.items():
            if _varied([m[0] for m in members.values()], rules_, MIN_COMBO_TRACKS):
                combos.append((g["name"], d, members))
    combos.sort(key=lambda c: -len(c[2]))
    for genre_name, d, members in combos[:MAX_COMBOS]:
        key = f"genre-decade:{genre_norm.slug(genre_name)}:{d}"
        order = _shuffled_members(members, key)
        rows = _capped(((t, members[t][0], f"{genre_name} · {members[t][1]}") for t in order), len(members))
        name, name_en = _both("{name} der {d}er", name=genre_name, d=_short(d))
        description, description_en = _both(
            "{name} aus den Jahren {start} bis {end}.", name=genre_name, start=d, end=d + 9
        )
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": name,
                "name_en": name_en,
                "description": description,
                "description_en": description_en,
                "items": rows,
            }
        )
    return specs


def _style_specs(conn: Connection, genre_playlists: set[str]) -> list[dict]:
    """Detected styles with enough tracks; one that only repeats a genre ("House") is left out."""
    specs = []
    rows = conn.execute(
        select(styles.c.id, styles.c.name, styles.c.slug, styles.c.genre)
        .where(styles.c.track_count >= MIN_STYLE_TRACKS)
        .order_by(styles.c.track_count.desc())
        .limit(MAX_STYLES)
    ).all()
    for s in rows:
        if s.name in genre_playlists:
            continue
        key = f"style:{s.slug}"
        stmt = (
            select(tracks.c.id)
            .join(track_styles, track_styles.c.track_id == tracks.c.id)
            .where(track_styles.c.style_id == s.id, track_styles.c.prob >= MIN_STYLE_PROB, _present())
        )
        ids = [r[0] for r in conn.execute(_shuffled(stmt, key))]
        description, description_en = (
            _both("Vom Klang her als {name} erkannt (gehört zu {genre}).", name=s.name, genre=s.genre)
            if s.genre
            else _both("Vom Klang her als {name} erkannt.", name=s.name)
        )
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": s.name,
                "name_en": s.name,
                "description": description,
                "description_en": description_en,
                "items": [(t, s.name) for t in ids],
            }
        )
    return specs


def _rule_specs(conn: Connection, analyzed: int, mood_columns: bool) -> list[dict]:
    if analyzed < MIN_ANALYZED_FOR_RULES:
        return []
    specs = []
    for key, (name, description, rule, fields) in BUILTIN_RULES.items():
        if key in ("happy", "sad", "aggressive", "relaxed") and not mood_columns:
            continue
        full_key = f"rule:{key}"
        rule = rules.validate({**rule, "limit": MAX_ITEMS, "order": "random"})
        ids = [r[0] for r in conn.execute(rules.query(rule, seed_of(full_key)))]
        if len(ids) < MIN_RULE_TRACKS:
            continue
        specs.append(
            {
                "key": full_key,
                "generator": "rule",
                "name": name,
                "name_en": tr("en", name),
                "description": description,
                "description_en": tr("en", description) if description else description,
                "rule": rule,
                "items": _with_reasons(conn, ids, fields),
            }
        )
    return specs


def kmeans(z: np.ndarray, k: int, seed: int = 7, iterations: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """Plain k-means++ / Lloyd in numpy. Returns (centroids, labels)."""
    rng = np.random.default_rng(seed)
    n = len(z)
    centroids = [z[rng.integers(n)]]
    for _ in range(1, k):
        d = np.min([((z - c) ** 2).sum(axis=1) for c in centroids], axis=0)
        total = d.sum()
        centroids.append(z[rng.choice(n, p=d / total)] if total > 0 else z[rng.integers(n)])
    centroids = np.array(centroids, dtype=np.float32)
    labels = np.zeros(n, dtype=np.int64)
    for iteration in range(iterations):
        new = sq_distances(z, centroids).argmin(axis=1)
        if iteration > 0 and np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            members = z[labels == j]
            if len(members):
                centroids[j] = members.mean(axis=0)
    return centroids, labels


def sq_distances(z: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Squared euclidean distances (n x k), without an n x k x d intermediate (fingerprints are 128 wide)."""
    d = (z**2).sum(axis=1)[:, None] - 2 * z @ centroids.T + (centroids**2).sum(axis=1)[None, :]
    return np.maximum(d, 0)


def _cluster_name(centroid: np.ndarray, names: list[str], lang: str) -> str:
    traits = []
    for j in np.argsort(-np.abs(centroid)):
        if abs(centroid[j]) < 0.45 or len(traits) == 2:
            break
        high, low = _TRAIT_WORDS[names[j]]
        word = high if centroid[j] > 0 else low
        if word:
            traits.append(tr(lang, word))
    return tr(lang, "Mix: {traits}", traits=" & ".join(traits) if traits else tr(lang, "bunt gemischt"))


def _cluster_specs(conn: Connection, analyzed: int) -> list[dict]:
    if analyzed < MIN_ANALYZED_FOR_CLUSTERS:
        return []
    ids, z, names = feature_matrix(conn)
    if len(ids) < MIN_ANALYZED_FOR_CLUSTERS:
        return []
    # Cluster a sample (k-means is O(n*k) per iteration, plenty fast for 100k but no need).
    rng = np.random.default_rng(1)
    sample = rng.choice(len(ids), size=min(len(ids), 20_000), replace=False)
    k = int(np.clip(round(np.sqrt(len(ids) / 60)), 3, 10))
    centroids, _ = kmeans(z[sample], k)
    # Stable keys: order clusters by tempo/energy so cluster:1 stays roughly the same mix.
    order = np.lexsort(
        (
            centroids[:, names.index("energy")] if "energy" in names else np.zeros(k),
            centroids[:, names.index("bpm")] if "bpm" in names else np.zeros(k),
        )
    )
    # Every track belongs to its nearest centroid; a mix holds only its own members (closest
    # first), so mixes do not overlap.
    all_dist = sq_distances(z, centroids)
    labels = all_dist.argmin(axis=1)
    specs, used_names = [], set()
    for rank, j in enumerate(order, start=1):
        members = np.flatnonzero(labels == j)
        if len(members) < MIN_RULE_TRACKS:
            continue
        nearest = members[np.argsort(all_dist[members, j])][:MIX_SIZE]
        name, name_en = _cluster_name(centroids[j], names, "de"), _cluster_name(centroids[j], names, "en")
        while name in used_names:
            name += " +"
            name_en += " +"
        used_names.add(name)
        description, description_en = _both("Ähnlich klingende Titel aus deiner Bibliothek, automatisch gruppiert.")
        track_ids = [int(ids[i]) for i in nearest]
        specs.append(
            {
                "key": f"cluster:{rank}",
                "generator": "cluster",
                "name": name,
                "name_en": name_en,
                "description": description,
                "description_en": description_en,
                "items": _with_reasons(conn, track_ids, ("bpm", "energy", "danceability")),
            }
        )
    return specs


def _top_styles(conn: Connection) -> dict[int, tuple[str, str]]:
    """track id -> (name, slug) of its most likely detected style."""
    rows = conn.execute(
        select(track_styles.c.track_id, styles.c.name, styles.c.slug)
        .join(styles, styles.c.id == track_styles.c.style_id)
        .where(track_styles.c.prob >= MIN_STYLE_PROB)
        .order_by(track_styles.c.track_id, track_styles.c.prob.desc())
    )
    top: dict[int, tuple[str, str]] = {}
    for r in rows:
        top.setdefault(r.track_id, (r.name, r.slug))
    return top


def _sound_cluster_specs(conn: Connection) -> list[dict]:
    """Mixes over the sound fingerprints: k-means on the unit-length PCA vectors, every track in
    its nearest mix only, named and keyed after the styles most common among its members."""
    ids, z = embedding_matrix(conn)
    if len(ids) < MIN_ANALYZED_FOR_CLUSTERS:
        return []
    rng = np.random.default_rng(1)
    sample = rng.choice(len(ids), size=min(len(ids), 20_000), replace=False)
    k = int(np.clip(round(np.sqrt(len(ids) / 40)), 4, 16))
    centroids, _ = kmeans(z[sample], k)
    all_dist = sq_distances(z, centroids)
    labels = all_dist.argmin(axis=1)
    top = _top_styles(conn)
    clusters = []
    for j in range(k):
        members = np.flatnonzero(labels == j)
        if len(members) < MIN_RULE_TRACKS:
            continue
        counts = Counter(top[int(ids[i])] for i in members if int(ids[i]) in top)
        # The styles that make up a real share of the mix, most common first.
        named = [st for st, n in counts.most_common(2) if n >= 0.15 * len(members)]
        clusters.append((len(members), j, members, named))
    specs, used_keys = [], set()
    # Biggest first, so the plain key (and name) goes to the main mix of a style.
    for _size, j, members, named in sorted(clusters, key=lambda c: (-c[0], c[1])):
        nearest = members[np.argsort(all_dist[members, j])][:MIX_SIZE]
        base = "sound:" + ("+".join(slug for _name, slug in named) or "mixed")
        key, n = base, 1
        while key in used_keys:
            n += 1
            key = f"{base}-{n}"
        used_keys.add(key)
        listed = " & ".join(name for name, _slug in named)
        name, name_en = (tr(lang, "Mix: {traits}", traits=listed or tr(lang, "bunt gemischt")) for lang in ("de", "en"))
        if n > 1:
            name += f" ({n})"
            name_en += f" ({n})"
        description, description_en = _both("Titel mit ähnlichem Klang-Fingerabdruck, automatisch gruppiert.")
        track_ids = [int(ids[i]) for i in nearest]
        specs.append(
            {
                "key": key,
                "generator": "sound",
                "name": name,
                "name_en": name_en,
                "description": description,
                "description_en": description_en,
                "items": [(t, top[t][0] if t in top else None) for t in track_ids],
            }
        )
    return specs


def _custom_spec(conn: Connection, row) -> dict | None:
    try:
        rule = rules.validate(json.loads(row.rule_json or "{}"))
    except Exception:
        return None
    ids = [r[0] for r in conn.execute(rules.query(rule, seed_of(row.key)))]
    fields = tuple(c["field"] for c in rule["conditions"] if rules.FIELDS[c["field"]].needs_analysis)[:3]
    return {
        "key": row.key,
        "generator": "custom",
        "name": row.name,
        "description": row.description,
        "rule": rule,
        "items": _with_reasons(conn, ids, fields or None, None),
    }


def _custom_specs(conn: Connection) -> list[dict]:
    rows = conn.execute(select(auto_playlists).where(auto_playlists.c.generator == "custom")).all()
    return [s for s in (_custom_spec(conn, r) for r in rows) if s]


def refresh_custom(conn: Connection, auto_id: int) -> None:
    """Re-evaluate one admin rule playlist now (after create or rule change)."""
    row = conn.execute(select(auto_playlists).where(auto_playlists.c.id == auto_id)).first()
    spec = _custom_spec(conn, row) if row is not None else None
    if spec:
        _store(conn, spec, now_ms())


# --- writing -------------------------------------------------------------------------------


def _store(conn: Connection, spec: dict, ts: int) -> str:
    existing = conn.execute(select(auto_playlists).where(auto_playlists.c.key == spec["key"])).first()
    if existing is not None and existing.status == "dismissed":
        return "skipped"
    status = spec.get("status", "suggested")
    items = spec["items"][:MAX_ITEMS]
    durations = {
        r.id: r.duration_ms
        for r in conn.execute(select(tracks.c.id, tracks.c.duration_ms).where(tracks.c.id.in_([t for t, _ in items])))
    }
    # generate_in computes the specs before it writes: a track may have been deleted meanwhile.
    items = [(t, reason) for t, reason in items if t in durations]
    track_ids = [t for t, _ in items]
    stats = (len(track_ids), sum(durations[t] or 0 for t in track_ids))
    # Genre and style playlists keep the cover made for them once (genre_covers); a new one shows
    # its first track's cover until genre_covers.refresh has made its own.
    cover = genre_covers.stored(conn, spec["key"]) if genre_covers.is_genre_key(spec["key"]) else None
    if cover is None and track_ids:
        cover = conn.execute(
            select(covers.c.hash).join(tracks, tracks.c.cover_id == covers.c.id).where(tracks.c.id == track_ids[0])
        ).scalar()
    detected = (
        conn.execute(
            select(func.count(func.distinct(track_genres.c.track_id))).where(
                track_genres.c.track_id.in_(track_ids), track_genres.c.source == "detected"
            )
        ).scalar_one()
        if spec["key"].startswith(("genre:", "genre-decade:"))
        else None
    )
    values = {
        "generator": spec["generator"],
        "detected_tracks": detected,
        "description": spec.get("description"),
        "description_en": spec.get("description_en"),
        "rule_json": json.dumps(spec["rule"]) if spec.get("rule") else None,
        "track_count": stats[0],
        "duration_ms": stats[1],
        "cover_hash": cover,
        "generated_at": ts,
        "updated_at": ts,
    }
    if existing is None:
        playlist_id = conn.execute(
            insert(auto_playlists).values(
                key=spec["key"],
                name=spec["name"],
                name_en=spec.get("name_en"),
                status=status,
                access="all",
                created_at=ts,
                **values,
            )
        ).inserted_primary_key[0]
        outcome = "created"
    else:
        playlist_id = existing.id
        if not existing.name_locked:
            values["name"] = spec["name"]
            values["name_en"] = spec.get("name_en")
        if status == "published" and existing.status == "suggested":
            values["status"] = "published"  # genre playlists from before they were published at once
        conn.execute(update(auto_playlists).where(auto_playlists.c.id == playlist_id).values(**values))
        conn.execute(delete(auto_playlist_items).where(auto_playlist_items.c.auto_playlist_id == playlist_id))
        outcome = "updated"
    if items:
        conn.execute(
            insert(auto_playlist_items),
            [
                {"auto_playlist_id": playlist_id, "rank": i, "track_id": t, "reason": reason}
                for i, (t, reason) in enumerate(items)
            ],
        )
    return outcome


def _specs(conn: Connection) -> tuple[str, int, list[dict]]:
    """What the auto-playlists should contain now (only reads): (source, analyzed tracks, specs)."""
    analyzed = conn.execute(
        select(func.count()).select_from(track_features).where(track_features.c.status == "ok")
    ).scalar_one()
    mood_columns = (
        conn.execute(
            select(func.count()).select_from(track_features).where(track_features.c.mood_happy.is_not(None))
        ).scalar_one()
        > 0
    )
    src = source(conn)
    # The radio sources' switches (analysis/sources.py) also decide which mixes there are.
    radio_sources = sources.load(conn)
    analyzed_for_mixes = analyzed if radio_sources["features"].on else 0  # 0: no mixes, see _cluster_specs
    if src == "sound":
        # Without genre playlists a style may share a genre's name ("House"), so none is left out.
        specs = [
            *_family_specs(conn, detected_only=True),
            *_style_specs(conn, set()),
            *(_sound_cluster_specs(conn) if radio_sources["sound"].on else []),
            *_custom_specs(conn),
        ]
    else:
        specs = [
            *_family_specs(conn, detected_only=False),
            *_tag_specs(conn),
            *_rule_specs(conn, analyzed, mood_columns),
            *_cluster_specs(conn, analyzed_for_mixes),
            *_custom_specs(conn),
        ]
    return src, analyzed, specs


def _remove_gone(conn: Connection, produced: set[str]) -> int:
    """Suggestions that no longer qualify disappear; published ones stay (with their last tracks),
    except genre playlists: nobody chose to publish them, so they come and go with their genre."""
    automatic = auto_playlists.c.key.startswith("genre:") | auto_playlists.c.key.startswith("family:")
    gone = conn.execute(
        select(auto_playlists.c.id, auto_playlists.c.key).where(
            (auto_playlists.c.status == "suggested") | ((auto_playlists.c.status == "published") & automatic),
            auto_playlists.c.generator != "custom",
        )
    ).all()
    removed = 0
    for row in gone:
        if row.key not in produced:
            conn.execute(delete(auto_playlists).where(auto_playlists.c.id == row.id))
            removed += 1
    return removed


def generate(conn: Connection, store: CoverStore | None = None) -> dict:
    """Recompute all auto-playlists in one transaction (the worker uses generate_in).
    With `store`, genre and style playlists also get their own cover (genre_covers)."""
    ts = now_ms()
    src, analyzed, specs = _specs(conn)
    stats = {"created": 0, "updated": 0, "skipped": 0}
    for spec in specs:
        stats[_store(conn, spec, ts)] += 1
    stats["removed"] = _remove_gone(conn, {s["key"] for s in specs})
    stats["smart"] = refresh_smart_playlists(conn)
    if store is not None:
        stats["covers"] = genre_covers.refresh(conn, store)
    log.info("autoplaylists.generated", source=src, analyzed=analyzed, **stats)
    return stats


def generate_in(db: Database, store: CoverStore | None = None) -> dict:
    """Recompute all auto-playlists. Runs in the analysis worker after scans and analysis.
    Computes in a read snapshot and writes in short transactions: with a big library the
    computation takes a while, and holding the write lock that long made requests that write
    (session renewal, play history, ...) wait and then fail with "database is locked"."""
    with db.read() as conn:
        src, analyzed, specs = _specs(conn)
        smart = []
        for row in conn.execute(select(playlists.c.id, playlists.c.rule_json).where(playlists.c.kind == "smart")):
            try:
                smart.append((row.id, evaluate_smart(conn, row.id, row.rule_json)))
            except Exception:
                log.exception("autoplaylists.smart_failed", playlist_id=row.id)
    ts = now_ms()
    stats = {"created": 0, "updated": 0, "skipped": 0, "smart": 0}
    for i in range(0, len(specs), STORE_BATCH):
        with db.write() as conn:
            for spec in specs[i : i + STORE_BATCH]:
                stats[_store(conn, spec, ts)] += 1
    with db.write() as conn:
        stats["removed"] = _remove_gone(conn, {s["key"] for s in specs})
    for playlist_id, track_ids in smart:
        with db.write() as conn:
            present = set(conn.execute(select(tracks.c.id).where(tracks.c.id.in_(track_ids))).scalars())
            if store_smart_items(conn, playlist_id, [t for t in track_ids if t in present]):
                stats["smart"] += 1
    if store is not None:
        stats["covers"] = genre_covers.refresh_in(db, store)
    log.info("autoplaylists.generated", source=src, analyzed=analyzed, **stats)
    return stats


def evaluate_smart(conn: Connection, playlist_id: int, rule_json: str) -> list[int]:
    rule = rules.validate(json.loads(rule_json))
    return [r[0] for r in conn.execute(rules.query(rule, seed_of(f"smart:{playlist_id}")))]


def store_smart_items(conn: Connection, playlist_id: int, track_ids: list[int]) -> bool:
    """Replace a smart playlist's items if they changed. Returns True when something changed."""
    current = [
        r[0]
        for r in conn.execute(
            select(playlist_items.c.track_id)
            .where(playlist_items.c.playlist_id == playlist_id)
            .order_by(playlist_items.c.position, playlist_items.c.id)
        )
    ]
    if current == track_ids:
        return False
    owner = conn.execute(select(playlists.c.owner_id).where(playlists.c.id == playlist_id)).scalar()
    conn.execute(delete(playlist_items).where(playlist_items.c.playlist_id == playlist_id))
    if track_ids:
        conn.execute(
            insert(playlist_items),
            [
                {
                    "playlist_id": playlist_id,
                    "track_id": t,
                    "position": (i + 1) * 1024,
                    "added_by": owner,
                    "added_at": now_ms(),
                    "auto": True,
                }
                for i, t in enumerate(track_ids)
            ],
        )
    stats = conn.execute(
        select(func.count(), func.coalesce(func.sum(tracks.c.duration_ms), 0))
        .select_from(playlist_items.join(tracks, tracks.c.id == playlist_items.c.track_id))
        .where(playlist_items.c.playlist_id == playlist_id)
    ).one()
    cover = (
        conn.execute(
            select(covers.c.hash).join(tracks, tracks.c.cover_id == covers.c.id).where(tracks.c.id == track_ids[0])
        ).scalar()
        if track_ids
        else None
    )
    conn.execute(
        update(playlists)
        .where(playlists.c.id == playlist_id)
        .values(
            item_count=stats[0],
            duration_ms=stats[1],
            cover_hash=cover,
            version=playlists.c.version + 1,
            updated_at=now_ms(),
        )
    )
    return True


def refresh_smart_playlists(conn: Connection) -> int:
    changed = 0
    for row in conn.execute(select(playlists.c.id, playlists.c.rule_json).where(playlists.c.kind == "smart")).all():
        try:
            if store_smart_items(conn, row.id, evaluate_smart(conn, row.id, row.rule_json)):
                changed += 1
        except Exception:
            log.exception("autoplaylists.smart_failed", playlist_id=row.id)
    return changed
