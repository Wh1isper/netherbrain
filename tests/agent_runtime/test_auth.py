"""Tests for Bearer token authentication middleware."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.app import app
from netherbrain.agent_runtime.deps import get_db
from netherbrain.agent_runtime.managers.sessions import SessionManager
from netherbrain.agent_runtime.registry import SessionRegistry
from netherbrain.agent_runtime.store.local import LocalStateStore

AUTH_TOKEN = "test-auth-token"  # noqa: S105


@pytest.fixture
async def auth_client(db_session: AsyncSession, tmp_path: object) -> AsyncIterator[AsyncClient]:
    """Client with auth token configured but NO default Authorization header."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.auth_token = AUTH_TOKEN
    app.state.db_engine = None
    app.state.db_session_factory = None
    app.state.redis = None
    app.state.session_manager = SessionManager(
        store=LocalStateStore(tmp_path),
        registry=SessionRegistry(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# -- Health bypass -----------------------------------------------------------


@pytest.mark.integration
async def test_health_bypasses_auth(auth_client: AsyncClient) -> None:
    """GET /api/health should work without any Authorization header."""
    resp = await auth_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")


# -- Missing header ----------------------------------------------------------


@pytest.mark.integration
async def test_no_auth_header_returns_401(auth_client: AsyncClient) -> None:
    resp = await auth_client.get("/api/presets/list")
    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"]


# -- Wrong scheme ------------------------------------------------------------


@pytest.mark.integration
async def test_wrong_scheme_returns_401(auth_client: AsyncClient) -> None:
    resp = await auth_client.get(
        "/api/presets/list",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"]


# -- Invalid token -----------------------------------------------------------


@pytest.mark.integration
async def test_invalid_token_returns_401(auth_client: AsyncClient) -> None:
    resp = await auth_client.get(
        "/api/presets/list",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


# -- Valid token passes ------------------------------------------------------


@pytest.mark.integration
async def test_valid_token_passes(auth_client: AsyncClient) -> None:
    resp = await auth_client.get(
        "/api/presets/list",
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status_code == 200


# -- POST endpoints also require auth ----------------------------------------


@pytest.mark.integration
async def test_post_without_auth_returns_401(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(
        "/api/presets/create",
        json={"name": "test", "model": {}, "system_prompt": "hi"},
    )
    assert resp.status_code == 401


# -- No token configured (lifespan not run) -> skip auth ---------------------


@pytest.fixture
async def noauth_client(db_session: AsyncSession, tmp_path: object) -> AsyncIterator[AsyncClient]:
    """Client with NO auth_token on app.state (simulates missing lifespan)."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.auth_token = None
    app.state.db_engine = None
    app.state.db_session_factory = None
    app.state.redis = None
    app.state.session_manager = SessionManager(
        store=LocalStateStore(tmp_path),
        registry=SessionRegistry(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.integration
async def test_no_token_configured_skips_auth(noauth_client: AsyncClient) -> None:
    """When auth_token is None on app.state, middleware allows access."""
    resp = await noauth_client.get("/api/presets/list")
    assert resp.status_code == 200
