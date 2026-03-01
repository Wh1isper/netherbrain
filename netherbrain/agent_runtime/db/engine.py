"""Async SQLAlchemy engine and session factory.

Uses psycopg3 which supports both sync and async with the same
``postgresql+psycopg://`` URL.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: str, **kwargs: object) -> AsyncEngine:
    """Create an async SQLAlchemy engine with production-ready pool settings.

    Default pool parameters are tuned for a small homelab service:

    - **pool_size=5**: baseline connections kept open.
    - **max_overflow=10**: burst capacity above pool_size.
    - **pool_pre_ping=True**: test connections before checkout to handle
      server-side disconnects (PG restarts, idle timeouts).
    - **pool_recycle=3600**: recycle connections after 1 hour to avoid
      issues with load-balancers or firewalls that drop idle TCP.

    All defaults can be overridden via *kwargs*.
    """
    defaults = {
        "echo": False,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    }
    defaults.update(kwargs)  # type: ignore[arg-type]
    return create_async_engine(database_url, **defaults)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*.

    ``expire_on_commit=False`` so that ORM instances remain usable after
    commit without triggering lazy loads (important for async code where
    implicit IO is forbidden).
    """
    return async_sessionmaker(engine, expire_on_commit=False)
