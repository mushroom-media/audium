"""search: punctuation-free word forms; playlist covers

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21 18:30:00.000000
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FTS_COLUMNS = {
    "tracks_fts": ("title", "artist", "album"),
    "albums_fts": ("title", "artist"),
    "artists_fts": ("name",),
}
# Frozen copy of audium.db.search.fts5.searchable as of this revision.
_PART_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _searchable(value: str | None) -> str | None:
    if not value:
        return value
    joined = ["".join(p) for p in (_PART_RE.findall(w) for w in value.split()) if len(p) > 1]
    return f"{value} {' '.join(joined)}" if joined else value


def upgrade() -> None:
    with op.batch_alter_table("playlists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cover_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("cover_preset", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_playlists_cover_id_covers"), "covers", ["cover_id"], ["id"], ondelete="SET NULL"
        )
    _reindex_punctuation()


def _reindex_punctuation() -> None:
    """Add the joined word forms to existing index rows ("N.W.A." -> also "nwa")."""
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        return
    for table, columns in _FTS_COLUMNS.items():
        cols = ", ".join(columns)
        rows = conn.execute(sa.text(f"SELECT rowid, {cols} FROM {table}")).all()
        changed = []
        for row in rows:
            values = [_searchable(v) for v in row[1:]]
            if values != list(row[1:]):
                changed.append({"id": row[0], **{c: v for c, v in zip(columns, values, strict=True)}})
        if not changed:
            continue
        placeholders = ", ".join(f":{c}" for c in columns)
        delete = sa.text(f"DELETE FROM {table} WHERE rowid = :id")
        insert = sa.text(f"INSERT INTO {table}(rowid, {cols}) VALUES (:id, {placeholders})")
        for i in range(0, len(changed), 1000):
            chunk = changed[i : i + 1000]
            conn.execute(delete, [{"id": r["id"]} for r in chunk])
            conn.execute(insert, chunk)


def downgrade() -> None:
    # The extra word forms in the search index are harmless and stay.
    with op.batch_alter_table("playlists", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_playlists_cover_id_covers"), type_="foreignkey")
        batch_op.drop_column("cover_preset")
        batch_op.drop_column("cover_id")
