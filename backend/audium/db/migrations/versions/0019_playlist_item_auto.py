"""playlist_items.auto: the track was picked automatically (smart playlist, "fill automatically",
saved auto-playlist), not added by hand

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("playlist_items") as batch:
        batch.add_column(sa.Column("auto", sa.Boolean(), server_default=sa.false(), nullable=False))
    # Smart playlists and saved auto-playlists were filled automatically. Tracks added by hand to a
    # saved auto-playlist afterwards can no longer be told apart: they came later, so a newer added_at
    # than the first item marks them.
    op.execute(
        """
        UPDATE playlist_items SET auto = 1
        WHERE playlist_id IN (SELECT id FROM playlists WHERE kind = 'smart')
           OR (playlist_id IN (SELECT id FROM playlists WHERE kind = 'frozen_auto')
               AND added_at = (SELECT min(i.added_at) FROM playlist_items i
                               WHERE i.playlist_id = playlist_items.playlist_id))
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("playlist_items") as batch:
        batch.drop_column("auto")
