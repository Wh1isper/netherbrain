"""Alembic migration environment.

Reads the database URL from NetherSettings (NETHER_DATABASE_URL env var)
and runs migrations synchronously using psycopg3.
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool

from netherbrain.agent_runtime.db.tables import Base
from netherbrain.agent_runtime.settings import NetherSettings

# -- Alembic Config object ----------------------------------------------------
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -- Target metadata for autogenerate ----------------------------------------
target_metadata = Base.metadata

# -- Database URL from app settings -------------------------------------------
settings = NetherSettings()
if not settings.database_url:
    msg = "NETHER_DATABASE_URL is not set. Cannot run migrations."
    raise RuntimeError(msg)


def get_url() -> str:
    """Return the database URL, converting asyncpg dialect if needed."""
    url = settings.database_url
    if url is None:  # pragma: no cover
        msg = "database_url is None"
        raise RuntimeError(msg)
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    """Filter objects for autogenerate.

    Excludes tables that exist in the database but are not defined in our
    models, preventing Alembic from generating DROP TABLE for foreign tables.
    """
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to the database and applies migrations directly.
    """
    connectable = create_engine(
        get_url(),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
