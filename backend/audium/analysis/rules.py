"""Track rules: {"match": "all"|"any", "conditions": [{"field", "op", "value"}], "limit", "order"}.

Used by the built-in auto-playlists, by admin rule playlists and by users' smart playlists.
Fields and operators are a whitelist; values are validated; the result is a SQLAlchemy query,
never string-built SQL.
"""

from dataclasses import dataclass

from sqlalchemy import Select, and_, exists, func, not_, or_, select

from audium.analysis.features import KEYS
from audium.analysis.genres import slug as genre_slug
from audium.analysis.styles import MIN_STYLE_PROB
from audium.db.schema import albums, genres, styles, track_features, track_genres, track_styles, tracks
from audium.errors import BadRequest
from audium.i18n import tr
from audium.util import now_ms

MAX_LIMIT = 1000
DEFAULT_LIMIT = 200
MAX_CONDITIONS = 20
ORDERS = ("random", "added", "year", "title", "bpm", "energy")

NUM_OPS = ("=", "!=", "<", "<=", ">", ">=", "between")
TEXT_OPS = ("is", "is_not", "contains")


@dataclass(frozen=True)
class Field:
    name: str
    label: str  # UI label, German (translated in field_definitions)
    kind: str  # number | text | enum | scale (0..1 feature)
    ops: tuple[str, ...]
    options: tuple[str, ...] = ()
    needs_analysis: bool = False
    unit: str = ""


FIELDS: dict[str, Field] = {
    f.name: f
    for f in (
        Field("genre", "Genre", "text", ("is", "is_not")),
        Field("style", "Stil (erkannt)", "text", ("is", "is_not"), needs_analysis=True),
        Field("artist", "Künstler", "text", TEXT_OPS),
        Field("album", "Album", "text", TEXT_OPS),
        Field("title", "Titel", "text", ("contains",)),
        Field("year", "Jahr", "number", NUM_OPS),
        Field("added_days", "Hinzugefügt vor (Tage)", "number", ("<=", ">=")),
        Field("duration", "Länge", "number", NUM_OPS, unit="s"),
        Field("bpm", "Tempo", "number", NUM_OPS, needs_analysis=True, unit="BPM"),
        Field("energy", "Energie", "scale", NUM_OPS, needs_analysis=True),
        Field("danceability", "Tanzbarkeit", "scale", NUM_OPS, needs_analysis=True),
        Field("brightness", "Klangfarbe (hell)", "scale", NUM_OPS, needs_analysis=True),
        Field("dynamics", "Dynamik", "scale", NUM_OPS, needs_analysis=True),
        Field("key", "Tonart", "enum", ("is", "is_not"), options=KEYS, needs_analysis=True),
        Field("mode", "Tongeschlecht", "enum", ("is",), options=("major", "minor"), needs_analysis=True),
        Field("mood_happy", "Fröhlich", "scale", NUM_OPS, needs_analysis=True),
        Field("mood_sad", "Traurig", "scale", NUM_OPS, needs_analysis=True),
        Field("mood_aggressive", "Aggressiv", "scale", NUM_OPS, needs_analysis=True),
        Field("mood_relaxed", "Entspannt", "scale", NUM_OPS, needs_analysis=True),
    )
}

_FEATURE_COLUMNS = {
    "bpm", "energy", "danceability", "brightness", "dynamics", "key", "mode",
    "mood_happy", "mood_sad", "mood_aggressive", "mood_relaxed",
}  # fmt: skip


def _num(value, field: Field) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"{field.name}: a number is required") from exc
    if field.kind == "scale" and not 0 <= x <= 1:
        raise BadRequest(f"{field.name}: value must be between 0 and 1")
    return x


def validate(rule: dict) -> dict:
    """Normalized copy of `rule`, or BadRequest with a message for the editor."""
    if not isinstance(rule, dict):
        raise BadRequest("rule must be an object")
    match = rule.get("match", "all")
    if match not in ("all", "any"):
        raise BadRequest("match must be 'all' or 'any'")
    conditions = rule.get("conditions") or []
    if not isinstance(conditions, list) or not conditions:
        raise BadRequest("a rule needs at least one condition")
    if len(conditions) > MAX_CONDITIONS:
        raise BadRequest(f"at most {MAX_CONDITIONS} conditions")
    clean = []
    for c in conditions:
        if not isinstance(c, dict):
            raise BadRequest("every condition must be an object")
        field = FIELDS.get(c.get("field"))
        if field is None:
            raise BadRequest(f"unknown field {c.get('field')!r}")
        op = c.get("op")
        if op not in field.ops:
            raise BadRequest(f"{field.name}: operator must be one of {', '.join(field.ops)}")
        value = c.get("value")
        if op == "between":
            if not isinstance(value, list | tuple) or len(value) != 2:
                raise BadRequest(f"{field.name}: 'between' needs two values")
            lo, hi = sorted((_num(value[0], field), _num(value[1], field)))
            value = [lo, hi]
        elif field.kind in ("number", "scale"):
            value = _num(value, field)
        elif field.kind == "enum":
            if value not in field.options:
                raise BadRequest(f"{field.name}: value must be one of {', '.join(field.options)}")
        else:
            value = str(value or "").strip()[:200]
            if not value:
                raise BadRequest(f"{field.name}: a value is required")
        clean.append({"field": field.name, "op": op, "value": value})
    limit = rule.get("limit", DEFAULT_LIMIT)
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise BadRequest("limit must be a number") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise BadRequest(f"limit must be between 1 and {MAX_LIMIT}")
    order = rule.get("order", "random")
    if order not in ORDERS:
        raise BadRequest(f"order must be one of {', '.join(ORDERS)}")
    return {"match": match, "conditions": clean, "limit": limit, "order": order}


def _compare(col, op: str, value):
    return {
        "=": lambda: col == value,
        "!=": lambda: col != value,
        "<": lambda: col < value,
        "<=": lambda: col <= value,
        ">": lambda: col > value,
        ">=": lambda: col >= value,
        "between": lambda: col.between(value[0], value[1]),
    }[op]()


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _condition(c: dict):
    field, op, value = c["field"], c["op"], c["value"]
    if field in _FEATURE_COLUMNS:
        col = track_features.c[field]
        is_enum = field in ("key", "mode")
        cond = (col == value if op == "is" else col != value) if is_enum else _compare(col, op, value)
        return and_(track_features.c.status == "ok", cond)
    if field == "genre":
        has = exists().where(
            track_genres.c.track_id == tracks.c.id,
            track_genres.c.genre_id == genres.c.id,
            or_(func.lower(genres.c.name) == value.lower(), genres.c.slug == genre_slug(value)),
        )
        return has if op == "is" else not_(has)
    if field == "style":
        has = exists().where(
            track_styles.c.track_id == tracks.c.id,
            track_styles.c.style_id == styles.c.id,
            track_styles.c.prob >= MIN_STYLE_PROB,
            or_(func.lower(styles.c.name) == value.lower(), styles.c.slug == genre_slug(value)),
        )
        return has if op == "is" else not_(has)
    if field in ("artist", "title"):
        col = tracks.c.artist_name if field == "artist" else tracks.c.title
        return _text(col, op, value)
    if field == "album":
        sub = select(albums.c.id).where(_text(albums.c.title, op if op != "is_not" else "is", value))
        return tracks.c.album_id.not_in(sub) if op == "is_not" else tracks.c.album_id.in_(sub)
    if field == "year":
        return and_(tracks.c.year > 0, _compare(tracks.c.year, op, value))
    if field == "duration":
        ms = [v * 1000 for v in value] if op == "between" else value * 1000
        return _compare(tracks.c.duration_ms, op, ms)
    if field == "added_days":
        cutoff = now_ms() - int(value * 86_400_000)
        return tracks.c.added_at >= cutoff if op == "<=" else tracks.c.added_at < cutoff
    raise BadRequest(f"unsupported field {field}")  # pragma: no cover - validate() prevents this


def _text(col, op: str, value: str):
    if op == "contains":
        return col.ilike(_like(value), escape="\\")
    if op == "is":
        return func.lower(col) == value.lower()
    return func.lower(col) != value.lower()


def shuffle_key(seed: int):
    """Deterministic pseudo-random order per seed, computed in SQL (no ORDER BY RANDOM() scan
    of a temp table per page, and the order stays stable between page loads)."""
    return (tracks.c.id * 2654435761 + seed) % 4294967296


def query(rule: dict, seed: int = 0) -> Select:
    """SELECT tracks.id matching a *validated* rule, ordered and limited."""
    conds = [_condition(c) for c in rule["conditions"]]
    where = and_(*conds) if rule["match"] == "all" else or_(*conds)
    stmt = (
        select(tracks.c.id)
        .outerjoin(track_features, track_features.c.track_id == tracks.c.id)
        .where(tracks.c.missing_since.is_(None), where)
    )
    order = rule["order"]
    if order == "random":
        stmt = stmt.order_by(shuffle_key(seed))
    elif order == "added":
        stmt = stmt.order_by(tracks.c.added_at.desc(), tracks.c.id)
    elif order == "year":
        stmt = stmt.order_by(tracks.c.year.desc(), tracks.c.id)
    elif order == "title":
        stmt = stmt.order_by(tracks.c.title_sort, tracks.c.id)
    else:  # bpm / energy
        stmt = stmt.order_by(track_features.c[order].desc().nulls_last(), tracks.c.id)
    return stmt.limit(rule["limit"])


def uses_analysis(rule: dict) -> bool:
    return any(FIELDS[c["field"]].needs_analysis for c in rule["conditions"])


def field_definitions(lang: str = "de") -> list[dict]:
    return [
        {
            "name": f.name,
            "label": tr(lang, f.label),
            "kind": f.kind,
            "ops": list(f.ops),
            "options": list(f.options),
            "needs_analysis": f.needs_analysis,
            "unit": f.unit,
        }
        for f in FIELDS.values()
    ]
