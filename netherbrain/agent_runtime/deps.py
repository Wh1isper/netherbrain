"""FastAPI dependency injection for DB sessions and Redis.

Usage in route handlers::

    @router.post("/things")
    async def create_thing(db: DbSession, thing: ThingCreate) -> ThingResponse:
        ...

    @router.get("/stream-info")
    async def stream_info(redis: RedisClient) -> dict:
        ...

Dependencies raise HTTP 503 if the backing service was not configured
(NETHER_DATABASE_URL / NETHER_REDIS_URL unset).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session, closing it after the request.

    The caller (route handler) is responsible for calling ``session.commit()``
    on success.  If the handler raises, the session is simply closed and the
    implicit transaction is rolled back by the connection pool.
    """
    session_factory = request.app.state.db_session_factory
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (NETHER_DATABASE_URL is unset).",
        )
    session: AsyncSession = session_factory()
    try:
        yield session
    finally:
        await session.close()


async def get_redis(request: Request) -> aioredis.Redis:
    """Return the shared async Redis client.

    Unlike the DB session, Redis connections are pooled internally by
    redis-py -- no per-request lifecycle needed.
    """
    client: aioredis.Redis | None = request.app.state.redis
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis not configured (NETHER_REDIS_URL is unset).",
        )
    return client


# -- Annotated type aliases for concise route signatures ---------------------

DbSession = Annotated[AsyncSession, Depends(get_db)]
"""Annotated dependency: async SQLAlchemy session (auto-closed after request)."""

RedisClient = Annotated[aioredis.Redis, Depends(get_redis)]
"""Annotated dependency: shared async Redis client."""
