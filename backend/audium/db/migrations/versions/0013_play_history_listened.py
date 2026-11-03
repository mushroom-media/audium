"""play_history.listened_ms: the time a play really sounded

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL for older plays and Subsonic scrobbles: the statistics count the track's length then.
    with op.batch_alter_table("play_history", schema=None) as batch_op:
        batch_op.add_column(sa.Column("listened_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("play_history", schema=None) as batch_op:
        batch_op.drop_column("listened_ms")
