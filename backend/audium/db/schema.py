"""Table definitions (SQLAlchemy Core).

Conventions:
- Integer primary keys everywhere; timestamps are UTC unix milliseconds (BigInteger).
- Columns used for keyset pagination are NOT NULL (NULL breaks row-value comparison).
- `*_sort` / `*_norm` columns are precomputed with audium.util.sort_key / norm.
- Full-text search tables are SQLite-specific and live in the migrations (see db/search).
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    false,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

app_state = Table(
    "app_state",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
)

# --- Library -------------------------------------------------------------------------------

library_roots = Table(
    "library_roots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("path", Text, nullable=False, unique=True),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("status", Text, nullable=False, default="new"),  # new | online | offline
    Column("status_message", Text),
    Column("last_scan_at", BigInteger),
    Column("track_count", Integer, nullable=False, default=0),
    Column("created_at", BigInteger, nullable=False),
)

library_excludes = Table(
    "library_excludes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("root_id", Integer, ForeignKey("library_roots.id", ondelete="CASCADE"), nullable=False),
    Column("rel_path", Text, nullable=False),
    UniqueConstraint("root_id", "rel_path"),
)

covers = Table(
    "covers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("hash", Text, nullable=False, unique=True),
    Column("source", Text, nullable=False),  # embedded | folder | artist | upload (playlist covers)
    Column("width", Integer),
    Column("height", Integer),
    Column("color", Text),  # main color "#rrggbb", "" = none (black and white), NULL = not determined yet
    Column("created_at", BigInteger, nullable=False),
)

artists = Table(
    "artists",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_sort", Text, nullable=False),
    Column("name_norm", Text, nullable=False, unique=True),
    Column("mb_artist_id", Text),
    # The image shown for the artist: `image_id` if set, else the cover of the newest album.
    Column("cover_id", Integer, ForeignKey("covers.id", ondelete="SET NULL")),
    # artist.jpg/.png from the artist folder (migration 0008); `image_key` = where it was found
    # and its size/mtime, so unchanged files are not read again.
    Column("image_id", Integer, ForeignKey("covers.id", ondelete="SET NULL")),
    Column("image_key", Text),
    Column("album_count", Integer, nullable=False, default=0),
    Column("track_count", Integer, nullable=False, default=0),
    Column("created_at", BigInteger, nullable=False),
    Index(None, "name_sort", "id"),
)

albums = Table(
    "albums",
    metadata,
    Column("id", Integer, primary_key=True),
    # mb:<release id> | aa:<album artist>\x1f<title> | dir:<root>:<dir>\x1f<title>
    Column("group_key", Text, nullable=False, unique=True),
    Column("title", Text, nullable=False),
    Column("title_sort", Text, nullable=False),
    Column("album_artist_id", Integer, ForeignKey("artists.id"), nullable=False),
    Column("artist_sort", Text, nullable=False),
    Column("year", Integer, nullable=False, default=0),  # 0 = unknown
    Column("compilation", Boolean, nullable=False, default=False),
    Column("cover_id", Integer, ForeignKey("covers.id", ondelete="SET NULL")),
    Column("mb_release_id", Text),
    Column("track_count", Integer, nullable=False, default=0),
    Column("duration_ms", BigInteger, nullable=False, default=0),
    Column("added_at", BigInteger, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Index(None, "album_artist_id", "year", "id"),
)

tracks = Table(
    "tracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("root_id", Integer, ForeignKey("library_roots.id", ondelete="CASCADE"), nullable=False),
    Column("rel_path", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("mtime_ns", BigInteger, nullable=False),
    Column("quick_hash", Text, nullable=False),
    Column("container", Text),
    Column("codec", Text),
    Column("bitrate", Integer),
    Column("sample_rate", Integer),
    Column("bit_depth", Integer),
    Column("channels", Integer),
    Column("duration_ms", Integer, nullable=False, default=0),
    Column("title", Text, nullable=False),
    Column("title_sort", Text, nullable=False),
    Column("artist_name", Text, nullable=False),  # display string: "Main, Guest"
    Column("artist_id", Integer, ForeignKey("artists.id"), nullable=False),  # primary artist
    Column("album_id", Integer, ForeignKey("albums.id"), nullable=False),
    Column("track_no", Integer),
    Column("disc_no", Integer),
    Column("year", Integer, nullable=False, default=0),
    Column("date", Text),
    Column("genre_raw", Text),
    Column("cover_id", Integer, ForeignKey("covers.id", ondelete="SET NULL")),
    Column("mb_track_id", Text),
    Column("mb_recording_id", Text),
    Column("rg_track_gain", Float),
    Column("rg_track_peak", Float),
    Column("rg_album_gain", Float),
    Column("rg_album_peak", Float),
    Column("tag_status", Text, nullable=False),  # ok | partial | fallback | error
    Column("missing_since", BigInteger),
    Column("added_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    UniqueConstraint("root_id", "rel_path"),
    Index(None, "album_id", "disc_no", "track_no"),
    Index(None, "artist_id"),
    Index(None, "quick_hash", "size"),
)

# --- Partial indexes for list endpoints ------------------------------------------------------
#
# Lists only show present tracks / non-empty albums. An index restricted to exactly those rows
# lets SQLite answer "ORDER BY title_sort, id LIMIT 100 OFFSET 50000" from the index alone
# (2 ms at 100k tracks instead of >100 ms with a row lookup per skipped entry). The queries
# must repeat the same WHERE term (`missing_since IS NULL`, `track_count > 0`) to use them.


def _partial(name: str, *columns, where) -> Index:
    return Index(name, *columns, sqlite_where=where, postgresql_where=where)


_present = tracks.c.missing_since.is_(None)
_partial("ix_tracks_present_title", tracks.c.title_sort, tracks.c.id, where=_present)
_partial("ix_tracks_present_added", tracks.c.added_at, tracks.c.id, where=_present)
_partial("ix_tracks_present_year", tracks.c.year, tracks.c.id, where=_present)
# Only for purging; a full index on missing_since would lure the planner away from the above.
_partial("ix_tracks_missing", tracks.c.missing_since, where=tracks.c.missing_since.is_not(None))

_visible = albums.c.track_count > 0
_partial("ix_albums_visible_title", albums.c.title_sort, albums.c.id, where=_visible)
_partial("ix_albums_visible_artist", albums.c.artist_sort, albums.c.year, albums.c.id, where=_visible)
_partial("ix_albums_visible_year", albums.c.year, albums.c.id, where=_visible)
_partial("ix_albums_visible_added", albums.c.added_at, albums.c.id, where=_visible)

_partial("ix_artists_album_artists_name", artists.c.name_sort, artists.c.id, where=artists.c.album_count > 0)

track_artists = Table(
    "track_artists",
    metadata,
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
    Column("artist_id", Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False),
    Column("role", Text, nullable=False),  # main | feat
    Column("position", Integer, nullable=False, default=0),
    PrimaryKeyConstraint("track_id", "artist_id", "role"),
    Index(None, "artist_id"),
)

# --- Users & auth --------------------------------------------------------------------------

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", Text, nullable=False, unique=True),  # stored lower-case
    Column("display_name", Text, nullable=False),
    Column("password_hash", Text),  # NULL for future external (OIDC) accounts
    Column("role", Text, nullable=False),  # admin | user
    Column("status", Text, nullable=False),  # active | disabled
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("last_login_at", BigInteger),
)

user_settings = Table(
    "user_settings",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("settings_json", Text, nullable=False, default="{}"),
    Column("updated_at", BigInteger, nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("created_at", BigInteger, nullable=False),
    Column("last_seen_at", BigInteger, nullable=False),
    Column("expires_at", BigInteger, nullable=False),
    Column("user_agent", Text),
    Column("ip", Text),
    Index(None, "user_id"),
)

api_tokens = Table(
    "api_tokens",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("prefix", Text, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("last_used_at", BigInteger),
    Index(None, "user_id"),
)

invites = Table(
    "invites",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("role", Text, nullable=False),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", BigInteger, nullable=False),
    Column("expires_at", BigInteger, nullable=False),
    Column("used_by", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("used_at", BigInteger),
)

login_attempts = Table(
    "login_attempts",
    metadata,
    Column("key", Text, primary_key=True),  # ip:<addr> | user:<name>
    Column("window_start", BigInteger, nullable=False),
    Column("count", Integer, nullable=False),
)

# --- Jobs ----------------------------------------------------------------------------------

jobs = Table(
    "jobs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("queue", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("dedupe_key", Text),
    Column("priority", Integer, nullable=False, default=0),
    Column("status", Text, nullable=False),  # queued | running | done | failed | cancelled
    Column("progress", Integer, nullable=False, default=0),
    Column("total", Integer, nullable=False, default=0),
    Column("message", Text),
    Column("result_json", Text),
    Column("error", Text),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=3),
    Column("cancel_requested", Boolean, nullable=False, default=False),
    Column("worker_id", Text),
    Column("heartbeat_at", BigInteger),
    Column("run_after", BigInteger, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("started_at", BigInteger),
    Column("finished_at", BigInteger),
    Index(None, "queue", "status", "priority", "run_after"),
    Index(None, "dedupe_key"),
)

# --- Playlists, favorites, history (migration 0002) -----------------------------------------

playlists = Table(
    "playlists",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("visibility", Text, nullable=False, default="private"),  # private | users
    Column("kind", Text, nullable=False, default="manual"),  # manual | smart | frozen_auto (phase 4)
    Column("rule_json", Text),  # smart playlists (phase 4)
    Column("version", Integer, nullable=False, default=1),  # +1 on every change
    Column("item_count", Integer, nullable=False, default=0),
    Column("duration_ms", BigInteger, nullable=False, default=0),
    Column("cover_hash", Text),  # cover of the first track, denormalized for lists
    # Chosen by the owner (migration 0004): an uploaded image or one of the built-in designs.
    Column("cover_id", Integer, ForeignKey("covers.id", ondelete="SET NULL")),
    Column("cover_preset", Integer),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Index(None, "owner_id"),
    Index(None, "visibility"),
)

playlist_items = Table(
    "playlist_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("playlist_id", Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False),
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
    # Server-assigned, with gaps (see services/playlists.py). Ties are broken by id.
    Column("position", BigInteger, nullable=False),
    Column("added_by", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("added_at", BigInteger, nullable=False),
    Index(None, "playlist_id", "position", "id"),
    Index(None, "track_id"),
)

playlist_shares = Table(
    "playlist_shares",
    metadata,
    Column("playlist_id", Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("role", Text, nullable=False),  # viewer | editor
    Column("created_at", BigInteger, nullable=False),
    PrimaryKeyConstraint("playlist_id", "user_id"),
    Index(None, "user_id"),
)

# Change log for live updates and catch-up after a reconnect (SSE Last-Event-ID). No foreign
# key: the "deleted" event must outlive its playlist. Old rows are pruned.
playlist_events = Table(
    "playlist_events",
    metadata,
    Column("seq", Integer, primary_key=True),
    Column("playlist_id", Integer, nullable=False),
    Column("type", Text, nullable=False),
    Column("actor_id", Integer),
    Column("version", Integer, nullable=False),
    Column("recipients_json", Text, nullable=False),  # user ids, or "*" for everyone
    Column("at", BigInteger, nullable=False),
    Index(None, "at"),
)

favorites = Table(
    "favorites",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("item_type", Text, nullable=False),  # track | album | artist
    Column("item_id", Integer, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    PrimaryKeyConstraint("user_id", "item_type", "item_id"),
    Index(None, "user_id", "item_type", "created_at"),
)

play_history = Table(
    "play_history",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
    Column("played_at", BigInteger, nullable=False),
    Column("played_ms", Integer, nullable=False, default=0),
    # What the track was played from, e.g. "album:3", "playlist:7", "radio:artist:2" (migration 0006).
    Column("context", Text),
    # The app that played it, for plays reported through the Subsonic API (migration 0007).
    Column("client", Text),
    # The time it really sounded: no pauses, buffering or skipped parts (migration 0013). NULL:
    # not measured (older plays, Subsonic apps); the statistics count the track's length then.
    Column("listened_ms", Integer),
    Index(None, "user_id", "played_at"),
    Index(None, "track_id"),
)

# --- Genres, audio features, auto-playlists (migration 0003) ---------------------------------

genres = Table(
    "genres",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False, unique=True),
    Column("track_count", Integer, nullable=False, default=0),
)

track_genres = Table(
    "track_genres",
    metadata,
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
    Column("genre_id", Integer, ForeignKey("genres.id", ondelete="CASCADE"), nullable=False),
    Column("source", Text, nullable=False, default="tag", server_default="tag"),  # tag | detected
    Column("weight", Float, nullable=False, default=1.0, server_default="1"),  # share of a detected genre
    PrimaryKeyConstraint("track_id", "genre_id"),
    Index(None, "genre_id"),
)

# One row per analysed track. All descriptors are on fixed 0..1 scales (see analysis/features.py)
# so rules like "energy >= 0.7" mean the same thing in every library.
track_features = Table(
    "track_features",
    metadata,
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("analyzer", Text, nullable=False),  # essentia[+effnet][+moods]
    Column("analyzer_version", Integer, nullable=False),
    Column("status", Text, nullable=False),  # ok | failed
    Column("error", Text),
    Column("fingerprint", Text, nullable=False),  # size:mtime:quick_hash of the analysed file
    Column("bpm", Float),
    Column("key", Text),  # C, C#, ... B
    Column("mode", Text),  # major | minor
    Column("loudness", Float),  # dB (Essentia DynamicComplexity estimate)
    Column("energy", Float),
    Column("dynamics", Float),
    Column("danceability", Float),
    Column("brightness", Float),
    Column("mood_happy", Float),
    Column("mood_sad", Float),
    Column("mood_aggressive", Float),
    Column("mood_relaxed", Float),
    Column("analyzed_at", BigInteger, nullable=False),
    Index(None, "status"),
    Index(None, "bpm"),
    Index(None, "energy"),
)

# Audio fingerprint of a track (Discogs-EffNet embedding, mean over the analysed window): 1280
# float16 values. NULL vector = the model failed on this file (not retried until it changes).
track_embeddings = Table(
    "track_embeddings",
    metadata,
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("model", Text, nullable=False),
    Column("vector", LargeBinary),
)

# Detected Discogs styles (analysis/styles.py), created on first use.
styles = Table(
    "styles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("label", Text, nullable=False, unique=True),  # model label, e.g. "Electronic---Deep House"
    Column("name", Text, nullable=False),  # shown: "Deep House"
    Column("parent", Text, nullable=False),  # Discogs top genre: "Electronic"
    Column("genre", Text),  # audium genre it counts for: "House"; NULL = none
    Column("slug", Text, nullable=False, unique=True),
    Column("track_count", Integer, nullable=False, default=0),
)

track_styles = Table(
    "track_styles",
    metadata,
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
    Column("style_id", Integer, ForeignKey("styles.id", ondelete="CASCADE"), nullable=False),
    Column("prob", Float, nullable=False),
    PrimaryKeyConstraint("track_id", "style_id"),
    Index(None, "style_id", "prob"),
)

auto_playlists = Table(
    "auto_playlists",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("key", Text, nullable=False, unique=True),  # e.g. genre:rock, decade:1990, rule:workout
    Column("generator", Text, nullable=False),  # tag | rule | cluster | custom
    Column("name", Text, nullable=False),
    Column("name_locked", Boolean, nullable=False, default=False),  # renamed by the admin: keep it
    Column("description", Text),
    # The generated name and description in English (the ones above are German); null for the
    # admin's own rule playlists and before the next generation. See services/auto.py.
    Column("name_en", Text),
    Column("description_en", Text),
    Column("rule_json", Text),
    Column("status", Text, nullable=False),  # suggested | published | dismissed
    Column("access", Text, nullable=False, default="all"),  # all | restricted | admin_only
    Column("track_count", Integer, nullable=False, default=0),
    Column("duration_ms", BigInteger, nullable=False, default=0),
    Column("cover_hash", Text),
    Column("generated_at", BigInteger),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("detected_tracks", Integer),  # genre playlists: tracks in there by a detected genre
    Index(None, "status"),
)

auto_playlist_items = Table(
    "auto_playlist_items",
    metadata,
    Column("auto_playlist_id", Integer, ForeignKey("auto_playlists.id", ondelete="CASCADE"), nullable=False),
    Column("rank", Integer, nullable=False),
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
    Column("reason", Text),  # why the track is here, e.g. "128 BPM · hohe Energie"
    PrimaryKeyConstraint("auto_playlist_id", "rank"),
    Index(None, "track_id"),
)

auto_playlist_access = Table(
    "auto_playlist_access",
    metadata,
    Column("auto_playlist_id", Integer, ForeignKey("auto_playlists.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("auto_playlist_id", "user_id"),
)

# --- Subsonic API (migration 0007) ---------------------------------------------------------

# Passwords for Subsonic apps, separate from the login password. The token method needs the
# plain secret on the server, so it is stored encrypted (AES-GCM, key outside the database).
app_passwords = Table(
    "app_passwords",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("secret_enc", LargeBinary, nullable=False),
    Column("prefix", Text, nullable=False),  # first characters, so the user can tell them apart
    Column("created_at", BigInteger, nullable=False),
    Column("last_used_at", BigInteger),
    Column("last_client", Text),  # Subsonic parameter c, e.g. "Symfonium"
    Index(None, "user_id"),
)

# What a user was listening to, for continuing on another device (Subsonic savePlayQueue).
play_queue = Table(
    "play_queue",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("track_ids_json", Text, nullable=False),
    Column("current_track_id", Integer),
    Column("position_ms", BigInteger, nullable=False, default=0),
    Column("changed_by", Text),
    Column("updated_at", BigInteger, nullable=False),
)

# Artists whose fans also listen to an artist, from ListenBrainz (services/similar_artists.py),
# only pairs where both are in the library. `score`: 0..1, 1 = the closest one of that artist.
artist_similar = Table(
    "artist_similar",
    metadata,
    Column("artist_id", Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False),
    Column("similar_id", Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False),
    Column("score", Float, nullable=False),
    PrimaryKeyConstraint("artist_id", "similar_id"),
)

# When an artist was last asked for; `mbid` as used (from the tags or looked up by name).
artist_similar_status = Table(
    "artist_similar_status",
    metadata,
    Column("artist_id", Integer, ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True),
    Column("mbid", Text),
    Column("status", Text, nullable=False),  # ok | no_mbid | error
    Column("fetched_at", BigInteger, nullable=False),
)

# Tracks a user skipped early in a radio station (analysis/taste.py): they rank lower in later
# stations like that one. `station`: "track:3", "album:5" or "artist:2". Kept 180 days.
# `disliked`: marked "Mag ich nicht", which also keeps it out of that station altogether.
radio_skips = Table(
    "radio_skips",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("track_id", Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
    Column("station", Text, nullable=False),
    Column("skipped_at", BigInteger, nullable=False),
    Column("disliked", Boolean, nullable=False, default=False, server_default=false()),
    Index(None, "user_id", "track_id"),
    Index(None, "skipped_at"),
)
