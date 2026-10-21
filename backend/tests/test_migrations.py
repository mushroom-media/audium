from alembic import command
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
    engine.dispose()
    migrate(url, tmp_path / "backups")
    assert current_revision(url) == "0002"
    assert len(list((tmp_path / "backups").glob("audium-0001-*.db"))) == 1
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT username FROM users")).scalar() == "keep"
        # FTS tables survive (autogenerate must never touch them)
        assert conn.execute(text("SELECT rowid FROM artists_fts WHERE artists_fts MATCH 'bjor*'")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM playlists")).scalar() == 0
    engine.dispose()
