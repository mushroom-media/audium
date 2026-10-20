"""Full-text search. The only database-specific part of library access besides dialect.py.

A PostgreSQL implementation would provide the same functions on top of tsvector / pg_trgm.
"""

from audium.db.search.fts5 import (
    add_tracks,
    build_match_query,
    index_album,
    index_artist,
    index_track,
    remove_albums,
    remove_artists,
    remove_tracks,
    search_ids,
)

__all__ = [
    "add_tracks",
    "build_match_query",
    "index_album",
    "index_artist",
    "index_track",
    "remove_albums",
    "remove_artists",
    "remove_tracks",
    "search_ids",
]
