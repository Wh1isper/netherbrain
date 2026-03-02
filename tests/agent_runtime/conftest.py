"""Shared fixtures for agent-runtime integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.app import app
from netherbrain.agent_runtime.deps import get_db
from netherbrain.agent_runtime.managers.execution import ExecutionManager
from netherbrain.agent_runtime.managers.sessions import SessionManager
from netherbrain.agent_runtime.registry import SessionRegistry
from netherbrain.agent_runtime.settings import NetherSettings
from netherbrain.agent_runtime.store.local import LocalStateStore

TEST_AUTH_TOKEN = "test-token-for-integration"  # noqa: S105


@pytest.fixture
def test_registry() -> SessionRegistry:
    """Shared registry for tests that need to manipulate active sessions."""
    return SessionRegistry()


@pytest.fixture
async def client(
    db_session: AsyncSession, tmp_path: object, test_registry: SessionRegistry
) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired to the app with a test DB session.

    Overrides ``get_db`` so every request uses the savepoint-isolated
    ``db_session`` fixture from the root conftest.  The app lifespan does
    NOT run under ``ASGITransport``, so state fields are pre-set to None.
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    session_manager = SessionManager(
        store=LocalStateStore(tmp_path),
        registry=test_registry,
    )

    # Minimal settings for ExecutionManager (no real LLM calls).
    settings = MagicMock(spec=NetherSettings)

    # Pre-set state fields (lifespan does not run under ASGITransport).
    app.state.auth_token = TEST_AUTH_TOKEN
    app.state.db_engine = None
    app.state.db_session_factory = None
    app.state.redis = None
    app.state.session_manager = session_manager
    app.state.execution_manager = ExecutionManager(
        session_manager=session_manager,
        registry=test_registry,
        settings=settings,
        session_factory=MagicMock(),
        redis=None,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {TEST_AUTH_TOKEN}"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
