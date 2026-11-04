"""auto_playlists.name_en, description_en: the generated name and description in English

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("auto_playlists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("name_en", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("description_en", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auto_playlists", schema=None) as batch_op:
        batch_op.drop_column("description_en")
        batch_op.drop_column("name_en")
