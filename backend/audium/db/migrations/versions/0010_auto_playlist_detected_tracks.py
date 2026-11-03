"""auto_playlists.detected_tracks: stored when a playlist is generated

Counting them per request took seconds per genre playlist in big libraries (the Discover page
lists all of them, twice), so the generator stores the count with the playlist now.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-27 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("auto_playlists") as batch:
        batch.add_column(sa.Column("detected_tracks", sa.Integer(), nullable=True))
    # The playlists that exist now get theirs right away, not only at the next generation.
    op.execute(
        """
        UPDATE auto_playlists SET detected_tracks = (
            SELECT count(*) FROM auto_playlist_items i
            WHERE i.auto_playlist_id = auto_playlists.id AND EXISTS (
                SELECT 1 FROM track_genres g WHERE g.track_id = i.track_id AND g.source = 'detected'))
        WHERE key LIKE 'genre:%' OR key LIKE 'genre-decade:%'
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("auto_playlists") as batch:
        batch.drop_column("detected_tracks")
