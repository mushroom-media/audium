"""subsonic: app passwords, play queue, client of a play

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_passwords",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("last_used_at", sa.BigInteger(), nullable=True),
        sa.Column("last_client", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_app_passwords_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_passwords")),
    )
    with op.batch_alter_table("app_passwords", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_app_passwords_user_id"), ["user_id"], unique=False)

    op.create_table(
        "play_queue",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("track_ids_json", sa.Text(), nullable=False),
        sa.Column("current_track_id", sa.Integer(), nullable=True),
        sa.Column("position_ms", sa.BigInteger(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_play_queue_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_play_queue")),
    )

    with op.batch_alter_table("play_history", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("play_history", schema=None) as batch_op:
        batch_op.drop_column("client")
    op.drop_table("play_queue")
    with op.batch_alter_table("app_passwords", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_app_passwords_user_id"))
    op.drop_table("app_passwords")
