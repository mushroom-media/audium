"""artist_similar, artist_similar_status: similar artists from ListenBrainz

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-27 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artist_similar",
        sa.Column("artist_id", sa.Integer(), nullable=False),
        sa.Column("similar_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"], ["artists.id"], name=op.f("fk_artist_similar_artist_id_artists"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["similar_id"], ["artists.id"], name=op.f("fk_artist_similar_similar_id_artists"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("artist_id", "similar_id", name=op.f("pk_artist_similar")),
    )
    op.create_table(
        "artist_similar_status",
        sa.Column("artist_id", sa.Integer(), nullable=False),
        sa.Column("mbid", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"], ["artists.id"], name=op.f("fk_artist_similar_status_artist_id_artists"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("artist_id", name=op.f("pk_artist_similar_status")),
    )


def downgrade() -> None:
    op.drop_table("artist_similar_status")
    op.drop_table("artist_similar")
