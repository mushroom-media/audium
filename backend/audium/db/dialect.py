"""The few places where SQL differs between SQLite and PostgreSQL."""

from sqlalchemy import Connection, Table
from sqlalchemy.dialects import postgresql, sqlite


def insert_for(conn: Connection, table: Table):
    """Dialect-specific INSERT that supports .on_conflict_do_update / _do_nothing."""
    if conn.dialect.name == "postgresql":
        return postgresql.insert(table)
    return sqlite.insert(table)
