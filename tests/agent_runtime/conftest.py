"""Shared fixtures for agent-runtime integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.app import app
from netherbrain.agent_runtime.db.tables import User
from netherbrain.agent_runtime.deps import get_db
from netherbrain.agent_runtime.managers.execution import ExecutionManager
from netherbrain.agent_runtime.managers.sessions import SessionManager
from netherbrain.agent_runtime.middleware import BOOTSTRAP_ADMIN_ID
from netherbrain.agent_runtime.registry import SessionRegistry
from netherbrain.agent_runtime.settings import NetherSettings
from netherbrain.agent_runtime.store.local import LocalStateStore

TEST_AUTH_TOKEN = "test-token-for-integration"  # noqa: S105


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create the bootstrap admin user required by FK constraints.

    The ``client`` fixture authenticates as this user via root token.
    Tests that create conversations (directly or via SessionManager)
    must use this fixture to satisfy the ``conversations.user_id`` FK.
    """
    user = User(user_id=BOOTSTRAP_ADMIN_ID, display_name="Admin", role="admin")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def test_registry() -> SessionRegistry:
    """Shared registry for tests that need to manipulate active sessions."""
    return SessionRegistry()


@pytest.fixture
async def client(
    db_session: AsyncSession, tmp_path: object, test_registry: SessionRegistry, test_user: User
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
    app.state.jwt_secret = "test-jwt-secret-for-integration-32bytes!"  # noqa: S105
    app.state.jwt_expiry_days = 7
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
