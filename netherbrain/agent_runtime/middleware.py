"""ASGI middleware for the agent runtime."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from sqlalchemy import select
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from netherbrain.agent_runtime.auth import AuthContext
from netherbrain.agent_runtime.models.enums import UserRole

# Root token key_id constant.
ROOT_KEY_ID = "root"

# JWT key_id constant.
JWT_KEY_ID = "jwt"

# Bootstrap admin user_id (created on first startup).
BOOTSTRAP_ADMIN_ID = "admin"

# Paths that bypass authentication.
_AUTH_EXEMPT_PATHS = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
}


class BearerAuthMiddleware:
    """Pure ASGI middleware for Bearer token authentication.

    Supports three authentication methods (tried in order):
    1. **Root token**: ``NETHER_AUTH_TOKEN`` env var (constant-time comparison,
       no DB lookup).  Always maps to admin role.
    2. **JWT**: Signed tokens issued by ``/api/auth/login``.  Verified via
       signature + expiry, then DB check for ``user.is_active``.
    3. **API keys**: Database-backed keys (``nb_`` prefixed).  Resolved via
       SHA-256 hash lookup in the ``api_keys`` table.

    Sets ``scope["state"]["auth"]`` to an ``AuthContext`` instance on success.
    Admin tokens may include ``X-Nether-User-Id`` header for delegation.

    Uses raw ASGI (not BaseHTTPMiddleware) to avoid interfering with
    streaming responses (SSE, chunked transfer).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]

        # Skip non-API routes (static UI, SPA fallback).
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        # Skip auth-exempt endpoints.
        method = scope.get("method", "")
        if (method, path) in _AUTH_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        result = await _authenticate(scope)

        if isinstance(result, AuthContext):
            scope.setdefault("state", {})["auth"] = result
            await self.app(scope, receive, send)
        else:
            await result(scope, receive, send)


async def _authenticate(scope: Scope) -> AuthContext | JSONResponse:
    """Resolve authentication from the request scope.

    Returns ``AuthContext`` on success, or a ``JSONResponse`` error.
    """
    # Read expected root token from app state.
    try:
        root_token: str | None = scope["app"].state.auth_token
    except (KeyError, AttributeError):
        return JSONResponse(status_code=503, content={"detail": "Auth not initialized."})

    session_factory = getattr(scope["app"].state, "db_session_factory", None)

    # When no root token and no DB, auth is disabled (development mode).
    if root_token is None and session_factory is None:
        return AuthContext(user_id=BOOTSTRAP_ADMIN_ID, role=UserRole.ADMIN, key_id=ROOT_KEY_ID)

    # Extract Bearer token.
    headers = scope.get("headers", [])
    token = _extract_bearer_token(headers)

    if token is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or malformed Authorization header."},
        )

    # 1. Root token (constant-time, no DB).
    if root_token is not None and hmac.compare_digest(token, root_token):
        auth = AuthContext(user_id=BOOTSTRAP_ADMIN_ID, role=UserRole.ADMIN, key_id=ROOT_KEY_ID)
        return _apply_delegation(auth, headers)

    # 2. JWT (signature + DB active check).
    jwt_secret: str | None = getattr(scope["app"].state, "jwt_secret", None)
    if jwt_secret is not None:
        result = await _resolve_jwt_with_active_check(token, jwt_secret, session_factory)
        if result is not None:
            return result

    # 3. API key (DB lookup).
    if session_factory is not None:
        auth = await _resolve_api_key(session_factory, token)
        if auth is not None:
            return _apply_delegation(auth, headers)

    return JSONResponse(status_code=401, content={"detail": "Invalid authentication token."})


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _extract_bearer_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Extract the Bearer token from raw ASGI headers."""
    for name, value in headers:
        if name == b"authorization":
            decoded = value.decode("latin-1")
            if decoded.startswith("Bearer "):
                return decoded[7:]
            return None
    return None


def _apply_delegation(
    auth: AuthContext,
    headers: list[tuple[bytes, bytes]],
) -> AuthContext:
    """Apply X-Nether-User-Id delegation for admin tokens.

    If the header is present and the caller is admin, override user_id
    while preserving admin role.  Non-admin callers are silently ignored
    (the header has no effect).
    """
    if not auth.is_admin:
        return auth

    for name, value in headers:
        if name == b"x-nether-user-id":
            target_user_id = value.decode("latin-1").strip()
            if target_user_id:
                return AuthContext(
                    user_id=target_user_id,
                    role=UserRole.ADMIN,
                    key_id=auth.key_id,
                )
    return auth


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key for DB lookup."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _resolve_jwt(token: str, secret: str) -> AuthContext | None:
    """Verify a JWT token and return AuthContext if valid."""
    from netherbrain.agent_runtime.managers.users import verify_jwt

    payload = verify_jwt(token, secret=secret)
    if payload is None:
        return None

    user_id = payload.get("user_id")
    role_str = payload.get("role")
    if not user_id or not role_str:
        return None

    try:
        role = UserRole(role_str)
    except ValueError:
        return None

    return AuthContext(user_id=user_id, role=role, key_id=JWT_KEY_ID)


async def _resolve_jwt_with_active_check(
    token: str,
    secret: str,
    session_factory: object | None,
) -> AuthContext | JSONResponse | None:
    """Resolve JWT and check user is still active.

    Returns:
    - ``AuthContext`` on success
    - ``JSONResponse(401)`` if user is deactivated
    - ``None`` if token is not a valid JWT (try next auth method)
    """
    auth = _resolve_jwt(token, secret)
    if auth is None:
        return None

    if session_factory is not None:
        is_active = await _check_user_active(session_factory, auth.user_id)
        if not is_active:
            return JSONResponse(status_code=401, content={"detail": "Account deactivated."})

    return auth


async def _check_user_active(session_factory: object, user_id: str) -> bool:
    """Check if a user is active in the database.

    Returns True if user exists and is active, False otherwise.
    """
    from netherbrain.agent_runtime.db.tables import User

    async with session_factory() as db:  # type: ignore[operator]
        user = await db.get(User, user_id)
        if user is None:
            return False
        return user.is_active


async def _resolve_api_key(session_factory: object, raw_key: str) -> AuthContext | None:
    """Look up an API key in the database and return AuthContext if valid."""
    from netherbrain.agent_runtime.db.tables import ApiKey, User

    key_hash = _hash_key(raw_key)

    async with session_factory() as db:  # type: ignore[operator]
        stmt = select(ApiKey, User).join(User, ApiKey.user_id == User.user_id).where(ApiKey.key_hash == key_hash)
        result = await db.execute(stmt)
        row = result.one_or_none()

        if row is None:
            return None

        api_key: ApiKey = row[0]
        user: User = row[1]

        # Check key is active.
        if not api_key.is_active:
            return None

        # Check key not expired.
        if api_key.expires_at is not None and api_key.expires_at < datetime.now(UTC):
            return None

        # Check user is active.
        if not user.is_active:
            return None

        return AuthContext(
            user_id=user.user_id,
            role=UserRole(user.role),
            key_id=api_key.key_id,
        )
