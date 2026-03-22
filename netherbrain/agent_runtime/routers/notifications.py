"""WebSocket endpoint for real-time notifications.

Authentication is handled by BearerAuthMiddleware which supports
``?token=`` query parameter for WebSocket connections.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, status
from loguru import logger

from netherbrain.agent_runtime.auth import AuthContext
from netherbrain.agent_runtime.notifications.handler import handle_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.websocket("")
async def notifications_ws(websocket: WebSocket) -> None:
    """Real-time notification WebSocket.

    Broadcasts all session lifecycle, mailbox, and conversation update
    events to connected clients via Redis Pub/Sub.

    Query parameters:
    - ``token``: Auth token (required, handled by middleware).
    """
    # -- Auth ------------------------------------------------------------------
    auth: AuthContext | None = getattr(websocket.state, "auth", None)
    if auth is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # -- Redis -----------------------------------------------------------------
    redis = websocket.app.state.redis
    if redis is None:
        logger.warning("Notification WS rejected: Redis not configured")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    logger.info("Notification WS: connected (user={})", auth.user_id)
    await handle_notifications(websocket, redis)
    logger.info("Notification WS: disconnected (user={})", auth.user_id)
