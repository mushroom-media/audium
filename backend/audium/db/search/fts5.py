"""SQLite FTS5 search.

Tables (created in migration 0001):
  tracks_fts(title, artist, album)  rowid = tracks.id
  albums_fts(title, artist)         rowid = albums.id
  artists_fts(name)                 rowid = artists.id
All use unicode61 with diacritics removal and prefix indexes for 2 and 3 characters, so
"bjor" finds "Björk" via index lookups instead of a table scan.

Punctuation: the tokenizer splits "N.W.A." into n/w/a and "AC/DC" into ac/dc. The indexed text
therefore also carries such words written together ("nwa", "acdc", see `searchable`), and a
query matches either the parts or the joined form, so "nwa", "n.w.a", "acdc", "ac/dc" and
"ac dc" all find the band.
"""

import re
from collections.abc import Iterable

from sqlalchemy import Connection, column, text

MIN_TOKEN_CHARS = 2
_MAX_TOKENS = 8
_MAX_JOINED_CHARS = 64
# What unicode61 keeps as token characters: letters and digits (underscore is a separator).
_PART_RE = re.compile(r"[^\W_]+", re.UNICODE)

_TABLES = {"track": "tracks_fts", "album": "albums_fts", "artist": "artists_fts"}


def searchable(value: str | None) -> str | None:
    """Index text: the value plus every word that contains punctuation written together."""
    if not value:
        return value
    joined = []
    for word in value.split():
        parts = _PART_RE.findall(word)
        if len(parts) > 1:
            joined.append("".join(parts))
    return f"{value} {' '.join(joined)}" if joined else value


def _word_term(parts: list[str]) -> str | None:
    joined = "".join(parts)
    if len(joined) < MIN_TOKEN_CHARS:
        return None
    # Quoting makes every token a literal string; FTS operators in the input stay inert.
    long_parts = [p for p in parts if len(p) >= MIN_TOKEN_CHARS]
    if len(parts) == 1 or not long_parts:
        return f'"{joined}"*'
    split = " ".join(f'"{p}"*' for p in long_parts)
    return f'("{joined}"* OR ({split}))'


def build_match_query(q: str) -> str | None:
    """User input -> FTS5 MATCH expression: every word must match as a prefix, either as typed
    or with its punctuation removed. Several words may also match written together."""
    words = [p for p in (_PART_RE.findall(w) for w in q.split()) if p][:_MAX_TOKENS]
    terms = [t for t in map(_word_term, words) if t]
    alternatives = [" ".join(terms)] if terms else []
    together = "".join("".join(p) for p in words)
    if len(words) > 1 and MIN_TOKEN_CHARS <= len(together) <= _MAX_JOINED_CHARS:
        alternatives.append(f'"{together}"*')  # "ac dc" -> AC/DC, "n w a" -> N.W.A.
    if not alternatives:
        return None
    if len(alternatives) == 1:
        return alternatives[0]
    return " OR ".join(f"({a})" for a in alternatives)


def index_track(conn: Connection, track_id: int, title: str, artist: str, album: str) -> None:
    conn.execute(text("DELETE FROM tracks_fts WHERE rowid = :id"), {"id": track_id})
    add_tracks(conn, [(track_id, title, artist, album)])


def add_tracks(conn: Connection, rows: list[tuple[int, str, str, str]]) -> None:
    """Bulk insert (id, title, artist, album) for tracks that have no index entry yet."""
    if rows:
        conn.execute(
            text("INSERT INTO tracks_fts(rowid, title, artist, album) VALUES (:id, :t, :a, :al)"),
            [{"id": i, "t": searchable(t), "a": searchable(a), "al": searchable(al)} for i, t, a, al in rows],
        )


def index_album(conn: Connection, album_id: int, title: str, artist: str) -> None:
    conn.execute(text("DELETE FROM albums_fts WHERE rowid = :id"), {"id": album_id})
    conn.execute(
        text("INSERT INTO albums_fts(rowid, title, artist) VALUES (:id, :t, :a)"),
        {"id": album_id, "t": searchable(title), "a": searchable(artist)},
    )


def index_artist(conn: Connection, artist_id: int, name: str) -> None:
    conn.execute(text("DELETE FROM artists_fts WHERE rowid = :id"), {"id": artist_id})
    conn.execute(
        text("INSERT INTO artists_fts(rowid, name) VALUES (:id, :n)"), {"id": artist_id, "n": searchable(name)}
    )


def _remove(conn: Connection, table: str, ids: Iterable[int]) -> None:
    ids = list(ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        params = {f"p{n}": v for n, v in enumerate(chunk)}
        placeholders = ", ".join(f":p{n}" for n in range(len(chunk)))
        conn.execute(text(f"DELETE FROM {table} WHERE rowid IN ({placeholders})"), params)


def remove_tracks(conn: Connection, ids: Iterable[int]) -> None:
    _remove(conn, "tracks_fts", ids)


def remove_albums(conn: Connection, ids: Iterable[int]) -> None:
    _remove(conn, "albums_fts", ids)


def remove_artists(conn: Connection, ids: Iterable[int]) -> None:
    _remove(conn, "artists_fts", ids)


_SEARCH_SQL = {
    "track": "SELECT tracks_fts.rowid FROM tracks_fts JOIN tracks t ON t.id = tracks_fts.rowid "
    "WHERE tracks_fts MATCH :q AND t.missing_since IS NULL",
    "album": "SELECT albums_fts.rowid FROM albums_fts JOIN albums a ON a.id = albums_fts.rowid "
    "WHERE albums_fts MATCH :q AND a.track_count > 0",
    "artist": "SELECT artists_fts.rowid FROM artists_fts JOIN artists a ON a.id = artists_fts.rowid "
    "WHERE artists_fts MATCH :q AND (a.track_count > 0 OR a.album_count > 0)",
}


def match_filter(kind: str, id_col, match: str):
    """WHERE clause keeping the rows of `id_col` whose index entry matches `match`, for filtering
    a list that keeps its own sort order (unlike `search_ids`, which ranks)."""
    table = _TABLES[kind]
    ids = text(f"SELECT rowid FROM {table} WHERE {table} MATCH :fts_q").bindparams(fts_q=match)
    return id_col.in_(ids.columns(column("rowid")))


def search_ids(conn: Connection, kind: str, match: str, limit: int, offset: int = 0) -> list[int]:
    """Ids of visible items matching `match`, best first (bm25)."""
    table = _TABLES[kind]
    rows = conn.execute(
        text(f"{_SEARCH_SQL[kind]} ORDER BY {table}.rank LIMIT :limit OFFSET :offset"),
        {"q": match, "limit": limit, "offset": offset},
    )
    return [r[0] for r in rows]
