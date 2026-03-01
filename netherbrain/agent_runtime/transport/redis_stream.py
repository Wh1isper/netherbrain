"""Redis Stream transport -- delivers AG-UI events via XADD.

Events are published to a Redis Stream keyed by session ID.  The stream
has a short TTL (ephemeral buffer for live consumption, not durable storage).
After session commit, display data is available from the PG session index.

All Redis keys use the ``nether:`` application prefix.  Stream keys follow
the pattern ``nether:stream:{session_id}``.

Usage::

    transport = RedisStreamTransport(redis, session_id)

    # Producer side (coordinator)
    await transport.send(event)
    ...
    await transport.close()  # sets TTL on the stream

    # Consumer side (bridge endpoint)
    # Uses XREAD on nether:stream:{session_id}
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ag_ui.core import BaseEvent

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Default stream TTL: 5 minutes.  Redis Streams are ephemeral buffers
# for live consumption; completed sessions use PG for display data.
DEFAULT_STREAM_TTL_SECONDS = 300

# Application key prefix.
KEY_PREFIX = "nether:stream"


def stream_key(session_id: str) -> str:
    """Build the Redis stream key for a session."""
    return f"{KEY_PREFIX}:{session_id}"


class RedisStreamTransport:
    """Redis Stream event transport via XADD.

    Each event is added as a Redis Stream entry with fields:

    - ``type``: event type string (for filtering)
    - ``data``: full JSON-serialized AG-UI event
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        session_id: str,
        *,
        ttl_seconds: int = DEFAULT_STREAM_TTL_SECONDS,
        max_stream_length: int = 10000,
    ) -> None:
        self._redis = redis
        self._session_id = session_id
        self._key = stream_key(session_id)
        self._ttl_seconds = ttl_seconds
        self._max_len = max_stream_length

    @property
    def key(self) -> str:
        """The Redis stream key for this session."""
        return self._key

    async def send(self, event: BaseEvent) -> None:
        """Publish an AG-UI event to the Redis Stream."""
        try:
            await self._redis.xadd(
                self._key,
                {
                    "type": event.type.value,
                    "data": event.model_dump_json(by_alias=True, exclude_none=True),
                },
                maxlen=self._max_len,
            )
        except Exception:
            logger.exception(
                "Failed to XADD event %s to stream %s",
                event.type,
                self._key,
            )

    async def close(self) -> None:
        """Set TTL on the stream after execution completes.

        The stream will auto-expire after ``ttl_seconds``.  Consumers
        must read events before expiry or use the PG session index for
        completed sessions.
        """
        try:
            await self._redis.expire(self._key, self._ttl_seconds)
            logger.debug(
                "Set TTL %ds on stream %s",
                self._ttl_seconds,
                self._key,
            )
        except Exception:
            logger.exception("Failed to set TTL on stream %s", self._key)
