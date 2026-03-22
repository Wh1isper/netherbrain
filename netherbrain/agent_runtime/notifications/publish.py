"""Publish notification events via Redis Pub/Sub.

Best-effort delivery: failures are logged and swallowed to avoid
disrupting the main execution path.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from netherbrain.agent_runtime.notifications import NotificationEvent

CHANNEL = "nether:notifications"


async def publish_notification(
    redis: aioredis.Redis | None,
    event: NotificationEvent,
) -> None:
    """Serialize and publish a notification event.

    No-op when Redis is unavailable.  Exceptions are logged
    and suppressed to keep the caller's critical path clean.
    """
    if redis is None:
        return
    try:
        payload = json.dumps(asdict(event), ensure_ascii=False)
        await redis.publish(CHANNEL, payload)
    except Exception:
        logger.warning("Failed to publish notification: {}", event.type, exc_info=True)
