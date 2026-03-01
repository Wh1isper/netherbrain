"""Shared test fixtures: testcontainers for PostgreSQL and Redis.

Integration tests use real PostgreSQL and Redis containers managed by
testcontainers-python. Containers are session-scoped (started once per
test run). Each test function gets an isolated DB session (via savepoint
rollback) and a flushed Redis client.

Requires Docker to be available. Tests needing containers should be
marked with ``@pytest.mark.integration``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from netherbrain.agent_runtime.settings import _get_settings_cached


def _set_env(key: str, value: str) -> None:
    """Set an env var and invalidate the settings cache."""
    os.environ[key] = value
    _get_settings_cached.cache_clear()


# ---------------------------------------------------------------------------
# Session-scoped: containers (started once, shared across all tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    """Start a PostgreSQL 17 container for the test session."""
    with PostgresContainer(
        image="postgres:17",
        username="test",
        password="test",
        dbname="netherbrain_test",
        driver="psycopg",
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    """Start a Redis 7 container for the test session."""
    with RedisContainer(image="redis:7") as r:
        yield r


# ---------------------------------------------------------------------------
# Session-scoped: connection URLs and schema migration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_url(pg_container: PostgresContainer) -> str:
    """PostgreSQL URL (psycopg3 dialect) with Alembic migrations applied."""
    url = pg_container.get_connection_url()
    _set_env("NETHER_DATABASE_URL", url)

    # Apply all migrations using the packaged alembic.ini (same config as CLI).
    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).parent.parent / "netherbrain" / "agent_runtime" / "alembic.ini"
    cfg = Config(str(ini_path))
    command.upgrade(cfg, "head")

    return url


@pytest.fixture(scope="session")
def redis_url(redis_container: RedisContainer) -> str:
    """Redis connection URL."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    url = f"redis://{host}:{port}/0"
    _set_env("NETHER_REDIS_URL", url)
    return url


# ---------------------------------------------------------------------------
# Session-scoped: async engine (shared across all tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def async_engine(pg_url: str) -> Iterator[AsyncEngine]:
    """Session-scoped async SQLAlchemy engine."""
    engine = create_async_engine(pg_url)
    yield engine
    engine.sync_engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped: DB session with savepoint rollback for test isolation
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Async SQLAlchemy session; all changes rolled back after the test.

    Uses ``join_transaction_mode="create_savepoint"`` so that session.commit()
    inside tested code only commits a savepoint, while the outer transaction
    is rolled back at teardown -- giving each test a clean database state.
    """
    async with async_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        yield session
        await session.close()
        await conn.rollback()


# ---------------------------------------------------------------------------
# Function-scoped: Redis client with flush
# ---------------------------------------------------------------------------


@pytest.fixture
async def redis_client(redis_url: str) -> AsyncIterator[aioredis.Redis]:
    """Async Redis client; database flushed after each test."""
    client = aioredis.from_url(redis_url)
    yield client
    await client.flushdb()
    await client.aclose()
