"""Transport protocol -- interface for event delivery backends.

Transports deliver ``ag_ui.core.BaseEvent`` instances to consumers.
Two implementations:

- **SSE**: Queue-backed Server-Sent Events over HTTP (pull model).
- **Redis Stream**: XADD to a keyed stream with short TTL (push model).

Both deliver identical event sequences.  Transport selection is per-request.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ag_ui.core import BaseEvent


@runtime_checkable
class EventTransport(Protocol):
    """Async interface for event delivery."""

    async def send(self, event: BaseEvent) -> None:
        """Deliver a single AG-UI event to the consumer."""
        ...

    async def close(self) -> None:
        """Signal that no more events will be sent.

        For SSE, this is a no-op (the terminal event closes the connection).
        For Redis, this may set the stream TTL.
        """
        ...
