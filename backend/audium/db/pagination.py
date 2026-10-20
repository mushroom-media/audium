"""Keyset pagination with an optional offset jump, in two steps.

Step 1 pages over the base table only: `SELECT id .. WHERE (k1, k2, id) > (:v1, :v2, :id)` on an
index with exactly these columns, so page 1000 costs the same as page 1. A virtual list that jumps
to the middle of the scrollbar uses `offset` once (an index-only skip, a few ms at 100k rows) and
continues from the cursor of that page.
Step 2 loads the joined details for just those ids. Joining before the offset would build the
joined row for every skipped entry.
"""

import base64
import json
from dataclasses import dataclass

from sqlalchemy import Column, Connection, Select, tuple_

from audium.errors import BadRequest


@dataclass(frozen=True)
class Sort:
    name: str
    columns: tuple  # all compared in the same direction; the last one must be unique (id)
    default_desc: bool = False


def encode_cursor(sort: str, desc: bool, values: list) -> str:
    raw = json.dumps([sort, int(desc), *values], separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, sort: Sort, desc: bool) -> list:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        name, d, *values = data
    except (ValueError, TypeError) as exc:
        raise BadRequest("invalid cursor") from exc
    if name != sort.name or bool(d) != desc or len(values) != len(sort.columns):
        raise BadRequest("cursor does not match sort/order")
    return values


def page_ids(
    conn: Connection,
    base: Select,
    sort: Sort,
    desc: bool,
    cursor: str | None,
    offset: int,
    limit: int,
) -> tuple[list[int], str | None]:
    """Step 1. `base` selects only the id column from the base table, with its filters."""
    keys = [c.label(f"_k{i}") for i, c in enumerate(sort.columns)]
    stmt = base.add_columns(*keys)
    if cursor:
        values = decode_cursor(cursor, sort, desc)
        row_value = tuple_(*sort.columns)
        stmt = stmt.where(row_value < tuple_(*values) if desc else row_value > tuple_(*values))
    elif offset:
        stmt = stmt.offset(offset)
    order = [c.desc() if desc else c.asc() for c in sort.columns]
    rows = conn.execute(stmt.order_by(*order).limit(limit + 1)).all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]._mapping
        next_cursor = encode_cursor(sort.name, desc, [last[f"_k{i}"] for i in range(len(keys))])
    return [r[0] for r in rows], next_cursor


def fetch_ordered(conn: Connection, detail: Select, id_col: Column, ids: list[int]) -> list:
    """Step 2. Rows of `detail` for `ids`, in the order of `ids`."""
    if not ids:
        return []
    rows = {r.id: r for r in conn.execute(detail.where(id_col.in_(ids)))}
    return [rows[i] for i in ids if i in rows]
