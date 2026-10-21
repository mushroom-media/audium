from alembic import context
from sqlalchemy import create_engine, pool

from audium.db.schema import metadata

config = context.config


def include_object(obj, name, type_, reflected, compare_to):
    # Tables that exist in the database but not in schema.py (the FTS5 tables and their
    # shadow tables, created by raw SQL in 0001) must never be dropped by autogenerate.
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=metadata,
        literal_binds=True,
        render_as_batch=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    with engine.connect() as conn:
        _run(conn)


def _run(connection) -> None:
    # render_as_batch: SQLite cannot ALTER most things, Alembic recreates the table instead.
    context.configure(
        connection=connection, target_metadata=metadata, render_as_batch=True, include_object=include_object
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
