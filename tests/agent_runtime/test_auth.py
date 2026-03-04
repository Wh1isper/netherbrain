"""Tests for Bearer token authentication middleware and JWT auth flow."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.app import app
from netherbrain.agent_runtime.deps import get_db
from netherbrain.agent_runtime.managers.sessions import SessionManager
from netherbrain.agent_runtime.managers.users import create_jwt, create_user
from netherbrain.agent_runtime.models.enums import UserRole
from netherbrain.agent_runtime.registry import SessionRegistry
from netherbrain.agent_runtime.store.local import LocalStateStore

AUTH_TOKEN = "test-auth-token"  # noqa: S105
JWT_SECRET = "test-jwt-secret-for-auth-tests-32bytes!"  # noqa: S105


@pytest.fixture
async def auth_client(db_session: AsyncSession, tmp_path: object) -> AsyncIterator[AsyncClient]:
    """Client with auth token configured but NO default Authorization header."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.auth_token = AUTH_TOKEN
    app.state.jwt_secret = JWT_SECRET
    app.state.jwt_expiry_days = 7
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
    app.state.jwt_secret = None
    app.state.jwt_expiry_days = 7
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


# -- JWT authentication ------------------------------------------------------


@pytest.mark.integration
async def test_jwt_auth_valid(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    """A valid JWT token should authenticate successfully."""
    # Create a user in the DB so /api/auth/me can find them.
    user, _pwd, _key = await create_user(db_session, user_id="jwt-user", display_name="JWT User", role=UserRole.USER)

    token = create_jwt(user.user_id, user.role, secret=JWT_SECRET, expiry_days=7)
    resp = await auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "jwt-user"
    assert data["role"] == "user"


@pytest.mark.integration
async def test_jwt_auth_expired(auth_client: AsyncClient) -> None:
    """An expired JWT should be rejected."""
    token = create_jwt("someone", "user", secret=JWT_SECRET, expiry_days=-1)
    resp = await auth_client.get(
        "/api/presets/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_jwt_auth_wrong_secret(auth_client: AsyncClient) -> None:
    """A JWT signed with a different secret should be rejected."""
    token = create_jwt("someone", "user", secret="wrong-secret", expiry_days=7)
    resp = await auth_client.get(
        "/api/presets/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


# -- Login flow ---------------------------------------------------------------


@pytest.mark.integration
async def test_login_success(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    """POST /api/auth/login with valid credentials returns JWT and user info."""
    _user, raw_password, _key = await create_user(db_session, user_id="login-user", display_name="Login User")

    resp = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "login-user", "password": raw_password},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["user_id"] == "login-user"

    # Verify the returned JWT works for authenticated requests.
    me_resp = await auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["user_id"] == "login-user"


@pytest.mark.integration
async def test_login_wrong_password(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    """POST /api/auth/login with wrong password returns 401."""
    await create_user(db_session, user_id="bad-pwd-user", display_name="Bad Pwd")

    resp = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "bad-pwd-user", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]


@pytest.mark.integration
async def test_login_nonexistent_user(auth_client: AsyncClient) -> None:
    """POST /api/auth/login with unknown user returns 401."""
    resp = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "ghost", "password": "anything"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_login_bypasses_auth_middleware(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    """POST /api/auth/login should work without Authorization header."""
    await create_user(db_session, user_id="no-header-user", display_name="No Header")

    # No Authorization header at all -- should still reach the endpoint.
    resp = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "no-header-user", "password": "wrong"},
    )
    # 401 means it reached the endpoint (not middleware rejection which would
    # say "Missing or malformed Authorization header").
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]


# -- Change password ----------------------------------------------------------


@pytest.mark.integration
async def test_change_password(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    """POST /api/auth/change-password should update the user's password."""
    _user, raw_password, _key = await create_user(db_session, user_id="chg-pwd-user", display_name="Chg Pwd")

    # Login first to get a JWT.
    login_resp = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "chg-pwd-user", "password": raw_password},
    )
    jwt_token = login_resp.json()["token"]
    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    # Change password.
    new_password = "my-new-password-123"  # noqa: S105
    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"old_password": raw_password, "new_password": new_password},
        headers=auth_headers,
    )
    assert resp.status_code == 204

    # Old password should fail.
    resp2 = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "chg-pwd-user", "password": raw_password},
    )
    assert resp2.status_code == 401

    # New password should work.
    resp3 = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "chg-pwd-user", "password": new_password},
    )
    assert resp3.status_code == 200


@pytest.mark.integration
async def test_change_password_wrong_old(auth_client: AsyncClient, db_session: AsyncSession) -> None:
    """Changing password with wrong old password returns 401."""
    _user, raw_password, _key = await create_user(db_session, user_id="wrong-old-user", display_name="Wrong Old")

    login_resp = await auth_client.post(
        "/api/auth/login",
        json={"user_id": "wrong-old-user", "password": raw_password},
    )
    jwt_token = login_resp.json()["token"]

    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"old_password": "not-the-right-one", "new_password": "doesnt-matter"},
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert resp.status_code == 401
