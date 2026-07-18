"""Alembic environment for AXit's PostgreSQL-only durable core."""

from __future__ import annotations

import os

from alembic import context
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL, engine_from_config, pool


config = context.config

# The first durable migration is deliberately SQL-first.  Domain correctness is
# enforced by PostgreSQL constraints and repositories, not by a parallel ORM
# model that could drift from the migration.
target_metadata = None


def _database_url() -> str:
    configured = config.attributes.get("database_url")
    if isinstance(configured, str) and configured:
        return configured
    environment_value = os.environ.get("DATABASE_URL")
    if environment_value:
        return environment_value
    raise RuntimeError("DATABASE_URL must be configured for Alembic")


def _sqlalchemy_database_url(database_url: str) -> str:
    """Convert a libpq DSN or URI into SQLAlchemy's psycopg-3 dialect URL."""

    connection_info = conninfo_to_dict(database_url)
    database = _as_optional_text(connection_info.pop("dbname", None))
    user = _as_optional_text(connection_info.pop("user", None))
    password = _as_optional_text(connection_info.pop("password", None))
    host = _as_optional_text(connection_info.pop("host", None))
    port_text = connection_info.pop("port", None)
    if not database:
        raise RuntimeError("PostgreSQL database name is required for Alembic")
    port = int(port_text) if port_text else None
    query = {key: str(value) for key, value in connection_info.items() if value}
    url = URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
        query=query,
    )
    # ``str(URL)`` intentionally redacts the password as ``***``. Alembic
    # receives this value in memory only, so render the actual connection URL
    # without ever printing or writing it to configuration.
    return url.render_as_string(hide_password=False)


def _as_optional_text(value: str | int | None) -> str | None:
    return None if value is None else str(value)


def run_migrations_offline() -> None:
    """Generate SQL without opening a database connection."""

    context.configure(
        url=_sqlalchemy_database_url(_database_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using Alembic's own short-lived connection."""

    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _sqlalchemy_database_url(_database_url())
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
