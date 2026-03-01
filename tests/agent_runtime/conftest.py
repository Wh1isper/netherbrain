"""Shared fixtures for agent-runtime integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.app import app
from netherbrain.agent_runtime.deps import get_db


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired to the app with a test DB session.

    Overrides ``get_db`` so every request uses the savepoint-isolated
    ``db_session`` fixture from the root conftest.  The app lifespan does
    NOT run under ``ASGITransport``, so state fields are pre-set to None.
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    # Pre-set state fields (lifespan does not run under ASGITransport).
    app.state.db_engine = None
    app.state.db_session_factory = None
    app.state.redis = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
