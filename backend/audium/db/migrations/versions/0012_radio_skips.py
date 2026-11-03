"""radio_skips: tracks skipped early in a radio station

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "radio_skips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("station", sa.Text(), nullable=False),
        sa.Column("skipped_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_radio_skips_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["track_id"], ["tracks.id"], name=op.f("fk_radio_skips_track_id_tracks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_radio_skips")),
    )
    op.create_index(op.f("ix_radio_skips_user_id_track_id"), "radio_skips", ["user_id", "track_id"])
    op.create_index(op.f("ix_radio_skips_skipped_at"), "radio_skips", ["skipped_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_radio_skips_skipped_at"), table_name="radio_skips")
    op.drop_index(op.f("ix_radio_skips_user_id_track_id"), table_name="radio_skips")
    op.drop_table("radio_skips")
