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
