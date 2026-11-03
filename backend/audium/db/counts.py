"""Cached COUNT(*) and A-Z indexes for list endpoints.

Virtual lists need the total up front to size the scrollbar. Counts are cached until the scanner
bumps the library generation, so scrolling never re-counts 100k rows.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Select, func, select

from audium.db.state import LIBRARY_GENERATION, get_state

_MAX_ENTRIES = 512


class CountCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[str, Any]] = OrderedDict()

    def count(self, conn: Connection, key: str, stmt: Select) -> int:
        return self.remember(
            conn, key, lambda: conn.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        )

    def remember(self, conn: Connection, key: str, compute: Callable[[], Any]) -> Any:
        """What `compute` returns, until the library changes. Callers must not change the result."""
        generation = get_state(conn, LIBRARY_GENERATION) or "0"
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] == generation:
                self._data.move_to_end(key)
                return hit[1]
        value = compute()
        with self._lock:
            self._data[key] = (generation, value)
            self._data.move_to_end(key)
            while len(self._data) > _MAX_ENTRIES:
                self._data.popitem(last=False)
        return value
