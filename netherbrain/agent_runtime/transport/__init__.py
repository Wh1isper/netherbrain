"""Transport layer (SSE / Redis Stream).

Provides two event delivery backends:

- ``SSETransport``: Queue-backed Server-Sent Events for direct HTTP consumers.
- ``RedisStreamTransport``: Redis Stream (XADD) for IM gateways and replay.

Both implement the ``EventTransport`` protocol and deliver identical
AG-UI event sequences.
"""

from netherbrain.agent_runtime.transport.base import EventTransport
from netherbrain.agent_runtime.transport.bridge import StreamGoneError, bridge_stream_to_sse
from netherbrain.agent_runtime.transport.redis_stream import (
    DEFAULT_STREAM_TTL_SECONDS,
    RedisStreamTransport,
    stream_key,
)
from netherbrain.agent_runtime.transport.sse import SSETransport

__all__ = [
    "DEFAULT_STREAM_TTL_SECONDS",
    "EventTransport",
    "RedisStreamTransport",
    "SSETransport",
    "StreamGoneError",
    "bridge_stream_to_sse",
    "stream_key",
]
