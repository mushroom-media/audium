from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from audium.db.migrate import alembic_config, current_revision, migrate


def test_upgrade_downgrade_upgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    migrate(url)
    assert current_revision(url) is not None
    command.downgrade(alembic_config(url), "base")
    assert current_revision(url) is None
    migrate(url)
    from sqlalchemy import create_engine

    names = set(inspect(create_engine(url)).get_table_names())
    assert {"tracks", "albums", "artists", "users", "jobs", "tracks_fts"} <= names


def test_backup_before_upgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    migrate(url)
    command.downgrade(alembic_config(url), "base")
    command.upgrade(alembic_config(url), "head")
    # Simulate an older schema version present on disk, then upgrade with backups enabled.
    command.downgrade(alembic_config(url), "base")
    migrate(url, tmp_path / "backups")
    # base -> head has no "current" revision, so no backup is taken for a fresh database
    assert not list((tmp_path / "backups").glob("*.db")) if (tmp_path / "backups").exists() else True


def test_upgrade_from_0001_keeps_data_and_takes_a_backup(tmp_path):
    """The path a running installation takes when it is updated (phase 2 -> 3)."""
    from sqlalchemy import create_engine, text

    url = f"sqlite:///{tmp_path / 'live.db'}"
    command.upgrade(alembic_config(url), "0001")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (username, display_name, password_hash, role, status, created_at, updated_at) "
                "VALUES ('keep', 'Keep', 'x', 'admin', 'active', 1, 1)"
            )
        )
        conn.execute(text("INSERT INTO artists_fts(rowid, name) VALUES (1, 'Björk')"))
        conn.execute(text("INSERT INTO artists_fts(rowid, name) VALUES (2, 'N.W.A.')"))
    engine.dispose()
    migrate(url, tmp_path / "backups")
    assert current_revision(url) == ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    assert len(list((tmp_path / "backups").glob("audium-0001-*.db"))) == 1
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT username FROM users")).scalar() == "keep"
        # FTS tables survive (autogenerate must never touch them)
        assert conn.execute(text("SELECT rowid FROM artists_fts WHERE artists_fts MATCH 'bjor*'")).scalar() == 1
        # 0004 adds the punctuation-free form to existing rows
        assert conn.execute(text("SELECT rowid FROM artists_fts WHERE artists_fts MATCH 'nwa*'")).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM playlists")).scalar() == 0
    engine.dispose()


def test_upgrade_from_0006_adds_subsonic_tables_and_artist_images(tmp_path):
    """Existing history keeps its rows (client = NULL, i.e. the web UI); the new tables are empty."""
    from sqlalchemy import create_engine, text

    url = f"sqlite:///{tmp_path / 'live.db'}"
    command.upgrade(alembic_config(url), "0006")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, display_name, password_hash, role, status, created_at, updated_at) "
                "VALUES (1, 'keep', 'Keep', 'x', 'admin', 'active', 1, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO library_roots (id, path, enabled, status, track_count, created_at) VALUES (1, '/m', 1, 'online', 0, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO artists (id, name, name_sort, name_norm, album_count, track_count, created_at) VALUES (1, 'A', 'a', 'a', 1, 1, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO albums (id, group_key, title, title_sort, album_artist_id, artist_sort, year, compilation, "
                "track_count, duration_ms, added_at, created_at) VALUES (1, 'k', 'T', 't', 1, 'a', 0, 0, 1, 0, 1, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO tracks (id, root_id, rel_path, size, mtime_ns, quick_hash, duration_ms, title, title_sort, "
                "artist_name, artist_id, album_id, year, tag_status, added_at, updated_at) "
                "VALUES (1, 1, 'a.mp3', 1, 1, 'h', 0, 'T', 't', 'A', 1, 1, 0, 'ok', 1, 1)"
            )
        )
        conn.execute(text("INSERT INTO play_history (user_id, track_id, played_at, played_ms) VALUES (1, 1, 5, 1000)"))
    engine.dispose()
    migrate(url, tmp_path / "backups")
    assert current_revision(url) == ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT played_at, client FROM play_history")).one() == (5, None)
        # 0013: older plays have no measured time (the statistics count the track's length)
        assert conn.execute(text("SELECT listened_ms FROM play_history")).scalar() is None
        assert conn.execute(text("SELECT count(*) FROM app_passwords")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM play_queue")).scalar() == 0
        # 0008: existing artists have no artist image yet (the next scan looks for artist.jpg)
        assert conn.execute(text("SELECT name, image_id, image_key FROM artists")).one() == ("A", None, None)
    engine.dispose()
