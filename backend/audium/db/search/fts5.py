"""SQLite FTS5 search.

Tables (created in migration 0001):
  tracks_fts(title, artist, album)  rowid = tracks.id
  albums_fts(title, artist)         rowid = albums.id
  artists_fts(name)                 rowid = artists.id
All use unicode61 with diacritics removal and prefix indexes for 2 and 3 characters, so
"bjor" finds "Björk" via index lookups instead of a table scan.
"""

import re
from collections.abc import Iterable

from sqlalchemy import Connection, text

MIN_TOKEN_CHARS = 2
_MAX_TOKENS = 8
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_TABLES = {"track": "tracks_fts", "album": "albums_fts", "artist": "artists_fts"}


def build_match_query(q: str) -> str | None:
    """User input -> FTS5 MATCH expression: every token must match as a prefix."""
    tokens = [t for t in _TOKEN_RE.findall(q) if len(t) >= MIN_TOKEN_CHARS][:_MAX_TOKENS]
    if not tokens:
        return None
    # Quoting makes every token a literal string; FTS operators in the input stay inert.
    return " ".join(f'"{t}"*' for t in tokens)


def index_track(conn: Connection, track_id: int, title: str, artist: str, album: str) -> None:
    conn.execute(text("DELETE FROM tracks_fts WHERE rowid = :id"), {"id": track_id})
    conn.execute(
        text("INSERT INTO tracks_fts(rowid, title, artist, album) VALUES (:id, :t, :a, :al)"),
        {"id": track_id, "t": title, "a": artist, "al": album},
    )


def add_tracks(conn: Connection, rows: list[tuple[int, str, str, str]]) -> None:
    """Bulk insert (id, title, artist, album) for tracks that have no index entry yet."""
    if rows:
        conn.execute(
            text("INSERT INTO tracks_fts(rowid, title, artist, album) VALUES (:id, :t, :a, :al)"),
            [{"id": i, "t": t, "a": a, "al": al} for i, t, a, al in rows],
        )


def index_album(conn: Connection, album_id: int, title: str, artist: str) -> None:
    conn.execute(text("DELETE FROM albums_fts WHERE rowid = :id"), {"id": album_id})
    conn.execute(
        text("INSERT INTO albums_fts(rowid, title, artist) VALUES (:id, :t, :a)"),
        {"id": album_id, "t": title, "a": artist},
    )


def index_artist(conn: Connection, artist_id: int, name: str) -> None:
    conn.execute(text("DELETE FROM artists_fts WHERE rowid = :id"), {"id": artist_id})
    conn.execute(text("INSERT INTO artists_fts(rowid, name) VALUES (:id, :n)"), {"id": artist_id, "n": name})


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


def search_ids(conn: Connection, kind: str, match: str, limit: int, offset: int = 0) -> list[int]:
    """Ids of visible items matching `match`, best first (bm25)."""
    table = _TABLES[kind]
    rows = conn.execute(
        text(f"{_SEARCH_SQL[kind]} ORDER BY {table}.rank LIMIT :limit OFFSET :offset"),
        {"q": match, "limit": limit, "offset": offset},
    )
    return [r[0] for r in rows]
