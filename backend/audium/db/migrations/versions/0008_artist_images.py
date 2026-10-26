"""artist images (artist.jpg / artist.png in the artist folder)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("artists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("image_key", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_artists_image_id_covers"), "covers", ["image_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("artists", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_artists_image_id_covers"), type_="foreignkey")
        batch_op.drop_column("image_key")
        batch_op.drop_column("image_id")
