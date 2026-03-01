"""Stream-to-SSE bridge -- converts Redis Stream to SSE with resume.

Provides ``bridge_stream_to_sse`` which reads events from a Redis Stream
and yields them as SSE-formatted dicts.  Supports ``Last-Event-ID`` for
resuming from a cursor position.

Usage in route handlers::

    @router.get("/sessions/{session_id}/events")
    async def handle_events(
        session_id: str,
        redis: RedisClient,
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    ):
        generator = bridge_stream_to_sse(
            redis, session_id, last_event_id=last_event_id,
        )
        return EventSourceResponse(generator)

Behavior by session state:

| State                        | Last-Event-ID | Behavior                           |
| ---------------------------- | ------------- | ---------------------------------- |
| Active, stream exists        | absent        | Replay from beginning + live tail  |
| Active, stream exists        | present       | Replay from cursor + live tail     |
| Completed, stream in TTL     | any           | Replay remaining + terminal + close|
| Session committed / expired  | any           | 410 Gone                           |
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from ag_ui.core import EventType

from netherbrain.agent_runtime.transport.redis_stream import stream_key

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# How often to poll for new events when tailing a live stream.
_POLL_INTERVAL_MS = 200

# Maximum idle time before giving up on a live stream (seconds).
# If no events arrive within this window, assume the producer is gone.
_MAX_IDLE_SECONDS = 300


class StreamGoneError(Exception):
    """Raised when the Redis Stream has expired or never existed."""

    def __init__(self, stream_key: str) -> None:
        super().__init__(f"Stream {stream_key} does not exist or has expired")


async def bridge_stream_to_sse(
    redis: aioredis.Redis,
    session_id: str,
    *,
    last_event_id: str | None = None,
    poll_interval_ms: int = _POLL_INTERVAL_MS,
    max_idle_seconds: float = _MAX_IDLE_SECONDS,
) -> AsyncIterator[dict[str, str]]:
    """Read events from a Redis Stream and yield SSE-formatted dicts.

    This generator:

    1. Replays historical events (from ``0`` or ``last_event_id``)
    2. Tails for new events using XREAD with blocking
    3. Stops after a terminal event (``run_finished`` / ``run_error``)
    4. Stops if idle for too long (producer likely gone)

    Raises ``StreamGoneError`` if the stream does not exist.
    """
    key, cursor = await _init_bridge(redis, session_id, last_event_id)

    idle_elapsed = 0.0
    poll_seconds = poll_interval_ms / 1000.0

    while True:
        # XREAD with block timeout for live tailing.
        entries = await redis.xread(
            {key: cursor},
            count=100,
            block=poll_interval_ms,
        )

        if not entries:
            # No new events.  Check idle timeout.
            idle_elapsed += poll_seconds
            if idle_elapsed >= max_idle_seconds:
                logger.info(
                    "Bridge idle timeout for session %s after %.0fs",
                    session_id,
                    idle_elapsed,
                )
                break

            # Check if stream still exists (might have expired).
            if not await redis.exists(key):
                logger.debug("Stream %s expired during bridge", key)
                break

            continue

        # Reset idle timer on activity.
        idle_elapsed = 0.0

        # entries format: [[key, [(stream_id, {field: value}), ...]]]
        for _stream_key, messages in entries:
            for stream_id, fields in messages:
                cursor = stream_id
                sse_event, is_terminal = _parse_stream_entry(stream_id, fields)
                if sse_event is not None:
                    yield sse_event
                if is_terminal:
                    return


async def _init_bridge(
    redis: aioredis.Redis,
    session_id: str,
    last_event_id: str | None,
) -> tuple[str, str]:
    """Validate stream existence and resolve the starting cursor."""
    key = stream_key(session_id)
    if not await redis.exists(key):
        raise StreamGoneError(key)

    cursor = "0-0"
    if last_event_id:
        cursor = await _find_cursor_by_event_id(redis, key, last_event_id)
    return key, cursor


_TERMINAL_EVENT_TYPES = {
    EventType.RUN_FINISHED.value,
    EventType.RUN_ERROR.value,
}


def _parse_stream_entry(
    stream_id: str | bytes,
    fields: dict[bytes | str, bytes | str],
) -> tuple[dict[str, str] | None, bool]:
    """Parse a single Redis Stream entry into an SSE dict.

    Returns ``(sse_event, is_terminal)``.  ``sse_event`` is *None* when
    the entry contains no ``data`` field.
    """
    data_bytes = fields.get(b"data") or fields.get("data")
    if data_bytes is None:
        return None, False

    data_str = data_bytes.decode() if isinstance(data_bytes, bytes) else data_bytes

    type_bytes = fields.get(b"type") or fields.get("type")
    type_str = (type_bytes.decode() if isinstance(type_bytes, bytes) else type_bytes) if type_bytes else None

    sse_id = stream_id if isinstance(stream_id, str) else stream_id.decode()
    sse_event = {"id": sse_id, "data": data_str}
    is_terminal = type_str is not None and type_str in _TERMINAL_EVENT_TYPES
    return sse_event, is_terminal


async def _find_cursor_by_event_id(
    redis: aioredis.Redis,
    key: str,
    target_event_id: str,
) -> str:
    """Find the Redis stream ID corresponding to a protocol event_id.

    Scans the stream to find the entry whose ``data`` contains the
    matching ``event_id``.  Returns the stream ID so XREAD resumes
    after that point.

    Falls back to ``0-0`` (replay from start) if not found.

    Note: For bridge reconnection, the ``Last-Event-ID`` is typically
    the Redis stream entry ID itself (set by the bridge as SSE ``id:``).
    This scan is a fallback for protocol-level event IDs.
    """
    # First, try interpreting the target as a Redis stream ID directly.
    # Bridge SSE uses stream entry IDs as the SSE id field.
    if "-" in target_event_id:
        # Likely a Redis stream ID (e.g., "1234567890123-0").
        return target_event_id

    # Fallback: scan for protocol event_id in data JSON.
    cursor = "0-0"
    while True:
        entries = await redis.xrange(key, min=cursor, count=100)
        if not entries:
            break

        for stream_id, fields in entries:
            cursor = stream_id
            data_bytes = fields.get(b"data") or fields.get("data")
            if data_bytes is None:
                continue
            data_str = data_bytes.decode() if isinstance(data_bytes, bytes) else data_bytes
            # Quick string check before full parse.
            if target_event_id in data_str:
                try:
                    parsed = json.loads(data_str)
                    if parsed.get("event_id") == target_event_id:
                        return stream_id
                except Exception:
                    logger.debug("Failed to parse event data in stream %s", key)
                    continue

        # If we got fewer than 100, we've reached the end.
        if len(entries) < 100:
            break

    # Not found -- replay from start.
    logger.debug("Event ID %s not found in stream %s, replaying from start", target_event_id, key)
    return "0-0"
