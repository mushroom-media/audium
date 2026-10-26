"""Generates auto-playlist suggestions and re-evaluates smart playlists.

Kinds (`generator`):
- tag:     per genre, per decade, the biggest genre x decade combinations ("Rock der 90er") and
           per detected style with enough tracks ("Deep House")
- rule:    built-in rules over audio features ("Workout", "Zum Entspannen", ...)
- cluster: k-means "mixes" over the feature vectors, named after their dominant traits
- sound:   k-means "mixes" over the sound fingerprints, named after their most common styles
- custom:  rule playlists the admin created; only re-evaluated here

The admin picks the source (state key SOURCE_STATE): "all" makes tag, rule, style and cluster
playlists; "sound" only what the sound recognition found (detected styles and sound mixes).

New playlists start as "suggested" (only the admin sees them) until the admin publishes them.
Existing ones keep status, access and an admin-given name; only their tracks are refreshed.
A "dismissed" playlist is never recreated.
"""

import json
import zlib
from collections import Counter

import numpy as np
from sqlalchemy import Connection, delete, func, insert, select, update

from audium.analysis import explain, rules
from audium.analysis.similarity import embedding_matrix, feature_matrix
from audium.analysis.styles import MIN_STYLE_PROB
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
from audium.logging import get_logger
from audium.util import now_ms

log = get_logger(__name__)

MAX_ITEMS = 300
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
        "Zum Entspannen", "Ruhig und langsam.",
        {"match": "all", "conditions": [
            {"field": "energy", "op": "<=", "value": 0.45},
            {"field": "bpm", "op": "<=", "value": 105},
        ]},
        ("bpm", "energy"),
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


def seed_of(key: str) -> int:
    return zlib.crc32(key.encode())


def decade_name(decade: int) -> str:
    return f"Die {str(decade)[2:]}er" if decade < 2000 else f"Die {decade}er"


def decade_suffix(decade: int) -> str:
    return f"der {str(decade)[2:]}er" if decade < 2000 else f"der {decade}er"


# --- helpers -------------------------------------------------------------------------------


def _present():
    return tracks.c.missing_since.is_(None)


def _shuffled(stmt, key: str):
    return stmt.order_by(rules.shuffle_key(seed_of(key))).limit(MAX_ITEMS)


def _with_reasons(conn: Connection, ids: list[int], fields: tuple[str, ...] | None, fixed: str | None = None):
    if fields is None:
        return [(t, fixed) for t in ids]
    rows = (
        {r.track_id: r for r in conn.execute(select(track_features).where(track_features.c.track_id.in_(ids)))}
        if ids
        else {}
    )
    return [(t, explain.describe(rows[t], fields) if t in rows else fixed) for t in ids]


def _tag_specs(conn: Connection) -> list[dict]:
    specs = []
    genre_rows = conn.execute(
        select(genres.c.id, genres.c.name, genres.c.slug, genres.c.track_count)
        .where(genres.c.track_count >= MIN_GENRE_TRACKS)
        .order_by(genres.c.track_count.desc())
    ).all()
    for g in genre_rows:
        key = f"genre:{g.slug}"
        stmt = (
            select(tracks.c.id)
            .join(track_genres, track_genres.c.track_id == tracks.c.id)
            .where(track_genres.c.genre_id == g.id, _present())
        )
        ids = [r[0] for r in conn.execute(_shuffled(stmt, key))]
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": g.name,
                "description": f"Alles aus dem Genre {g.name}.",
                "items": [(t, g.name) for t in ids],
            }
        )

    specs += _style_specs(conn, {g.name for g in genre_rows})

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
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": decade_name(d),
                "description": f"Musik aus den Jahren {d} bis {d + 9}.",
                "items": [(r.id, str(r.year)) for r in rows],
            }
        )

    combo_rows = conn.execute(
        select(genres.c.id, genres.c.name, genres.c.slug, decade.label("d"), func.count().label("n"))
        .select_from(
            track_genres.join(tracks, tracks.c.id == track_genres.c.track_id).join(
                genres, genres.c.id == track_genres.c.genre_id
            )
        )
        .where(_present(), tracks.c.year >= 1900)
        .group_by(genres.c.id, decade)
        .having(func.count() >= MIN_COMBO_TRACKS)
        .order_by(func.count().desc())
        .limit(MAX_COMBOS)
    ).all()
    for c in combo_rows:
        key = f"genre-decade:{c.slug}:{c.d}"
        stmt = (
            select(tracks.c.id, tracks.c.year)
            .join(track_genres, track_genres.c.track_id == tracks.c.id)
            .where(track_genres.c.genre_id == c.id, _present(), tracks.c.year.between(c.d, c.d + 9))
        )
        rows = conn.execute(stmt.order_by(rules.shuffle_key(seed_of(key))).limit(MAX_ITEMS)).all()
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": f"{c.name} {decade_suffix(c.d)}",
                "description": f"{c.name} aus den Jahren {c.d} bis {c.d + 9}.",
                "items": [(r.id, f"{c.name} · {r.year}") for r in rows],
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
        part_of = f" (gehört zu {s.genre})" if s.genre else ""
        specs.append(
            {
                "key": key,
                "generator": "tag",
                "name": s.name,
                "description": f"Vom Klang her als {s.name} erkannt{part_of}.",
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
                "description": description,
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


def _cluster_name(centroid: np.ndarray, names: list[str]) -> str:
    traits = []
    for j in np.argsort(-np.abs(centroid)):
        if abs(centroid[j]) < 0.45 or len(traits) == 2:
            break
        high, low = _TRAIT_WORDS[names[j]]
        word = high if centroid[j] > 0 else low
        if word:
            traits.append(word)
    return "Mix: " + (" & ".join(traits) if traits else "bunt gemischt")


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
        name = _cluster_name(centroids[j], names)
        while name in used_names:
            name += " +"
        used_names.add(name)
        track_ids = [int(ids[i]) for i in nearest]
        specs.append(
            {
                "key": f"cluster:{rank}",
                "generator": "cluster",
                "name": name,
                "description": "Ähnlich klingende Titel aus deiner Bibliothek, automatisch gruppiert.",
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
        name = "Mix: " + (" & ".join(name for name, _slug in named) or "bunt gemischt")
        if n > 1:
            name += f" ({n})"
        track_ids = [int(ids[i]) for i in nearest]
        specs.append(
            {
                "key": key,
                "generator": "sound",
                "name": name,
                "description": "Titel mit ähnlichem Klang-Fingerabdruck, automatisch gruppiert.",
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
    items = spec["items"][:MAX_ITEMS]
    track_ids = [t for t, _ in items]
    stats = (
        conn.execute(
            select(func.count(), func.coalesce(func.sum(tracks.c.duration_ms), 0)).where(tracks.c.id.in_(track_ids))
        ).one()
        if track_ids
        else (0, 0)
    )
    cover = (
        conn.execute(
            select(covers.c.hash).join(tracks, tracks.c.cover_id == covers.c.id).where(tracks.c.id == track_ids[0])
        ).scalar()
        if track_ids
        else None
    )
    values = {
        "generator": spec["generator"],
        "description": spec.get("description"),
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
                key=spec["key"], name=spec["name"], status="suggested", access="all", created_at=ts, **values
            )
        ).inserted_primary_key[0]
        outcome = "created"
    else:
        playlist_id = existing.id
        if not existing.name_locked:
            values["name"] = spec["name"]
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


def generate(conn: Connection) -> dict:
    """Recompute all auto-playlists. Runs in the analysis worker after scans and analysis."""
    ts = now_ms()
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
    if src == "sound":
        # Without genre playlists a style may share a genre's name ("House"), so none is left out.
        specs = [*_style_specs(conn, set()), *_sound_cluster_specs(conn), *_custom_specs(conn)]
    else:
        specs = [
            *_tag_specs(conn),
            *_rule_specs(conn, analyzed, mood_columns),
            *_cluster_specs(conn, analyzed),
            *_custom_specs(conn),
        ]
    produced = {s["key"] for s in specs}
    stats = {"created": 0, "updated": 0, "skipped": 0, "removed": 0}
    for spec in specs:
        stats[_store(conn, spec, ts)] += 1
    # Suggestions that no longer qualify disappear; published ones stay (with their last tracks).
    gone = conn.execute(
        select(auto_playlists.c.id, auto_playlists.c.key).where(
            auto_playlists.c.status == "suggested", auto_playlists.c.generator != "custom"
        )
    ).all()
    for row in gone:
        if row.key not in produced:
            conn.execute(delete(auto_playlists).where(auto_playlists.c.id == row.id))
            stats["removed"] += 1
    stats["smart"] = refresh_smart_playlists(conn)
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
