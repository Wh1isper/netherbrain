"""ASGI middleware for the agent runtime."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerAuthMiddleware:
    """Pure ASGI middleware for Bearer token authentication.

    Validates ``Authorization: Bearer {token}`` on all ``/api/*`` requests
    except ``GET /api/health``.  The expected token is read from
    ``app.state.auth_token`` at request time (set during lifespan startup).

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

        # Skip health endpoint (no auth required).
        if path == "/api/health" and scope.get("method") == "GET":
            await self.app(scope, receive, send)
            return

        # Read expected token from app state (set during lifespan startup).
        try:
            expected_token: str | None = scope["app"].state.auth_token
        except (KeyError, AttributeError):
            # Lifespan hasn't run or token not configured -- skip auth.
            await self.app(scope, receive, send)
            return

        if expected_token is None:
            await self.app(scope, receive, send)
            return

        # Extract and validate Bearer token.
        token = _extract_bearer_token(scope.get("headers", []))

        if token is None:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Missing or malformed Authorization header."},
            )
            await response(scope, receive, send)
            return

        if token != expected_token:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication token."},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _extract_bearer_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Extract the Bearer token from raw ASGI headers.

    Returns ``None`` if the Authorization header is missing or does not
    use the Bearer scheme.
    """
    for name, value in headers:
        if name == b"authorization":
            decoded = value.decode("latin-1")
            if decoded.startswith("Bearer "):
                return decoded[7:]
            return None  # Header present but wrong scheme.
    return None
