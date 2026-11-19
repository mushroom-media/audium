"""auto_playlist_covers: the cover made once per genre or style playlist

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-10 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auto_playlist_covers",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_auto_playlist_covers")),
    )


def downgrade() -> None:
    op.drop_table("auto_playlist_covers")
