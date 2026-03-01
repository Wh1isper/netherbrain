"""Async SQLAlchemy engine and session factory.

Uses psycopg3 which supports both sync and async with the same
``postgresql+psycopg://`` URL.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def create_engine(database_url: str, **kwargs) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        database_url: PostgreSQL connection string
            (e.g. ``postgresql+psycopg://user:pass@host/db``).
        **kwargs: Additional arguments passed to ``create_async_engine``.
    """
    return create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        **kwargs,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)
