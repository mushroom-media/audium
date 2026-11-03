"""artists.cover_id always falls back to the newest album cover

Whether an artist without an own picture shows that cover is a per-user choice now (the server
setting is only the default), so the fallback is always stored and picked per request.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE artists SET cover_id = coalesce(image_id, (
            SELECT a.cover_id FROM albums a
            WHERE a.album_artist_id = artists.id AND a.cover_id IS NOT NULL AND a.track_count > 0
            ORDER BY a.year DESC, a.id DESC LIMIT 1))
        """
    )


def downgrade() -> None:
    pass  # the fallback does no harm to the older code (it showed it with the setting "on")
