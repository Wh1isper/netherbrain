"""SSE transport -- delivers AG-UI events via Server-Sent Events.

Uses an ``asyncio.Queue`` as the bridge between the execution pipeline
(producer) and the SSE response generator (consumer).  The queue decouples
execution from HTTP delivery -- the agent runs to completion regardless
of consumer speed or disconnection.

Usage::

    transport = SSETransport(session_id)

    # Producer side (coordinator)
    await transport.send(event)
    ...
    await transport.close()

    # Consumer side (route handler)
    return EventSourceResponse(transport.event_generator())
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from ag_ui.core import BaseEvent

from netherbrain.agent_runtime.models.events import encode_sse, is_terminal

logger = logging.getLogger(__name__)

# Sentinel to signal end of stream.
_SENTINEL = object()


class SSETransport:
    """Queue-backed SSE event transport.

    Events are buffered in an asyncio queue.  The ``event_generator``
    method yields SSE-formatted dicts consumed by ``sse-starlette``'s
    ``EventSourceResponse``.
    """

    def __init__(self, session_id: str, *, max_queue_size: int = 1024) -> None:
        self._session_id = session_id
        self._queue: asyncio.Queue[BaseEvent | object] = asyncio.Queue(
            maxsize=max_queue_size,
        )
        self._closed = False

    async def send(self, event: BaseEvent) -> None:
        """Enqueue an AG-UI event for SSE delivery."""
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "SSE queue full for session %s, dropping event %s",
                self._session_id,
                event.type,
            )

    async def close(self) -> None:
        """Signal end of event stream.

        Uses ``put_nowait`` to avoid blocking when the queue is full
        (consumer slow or disconnected).  If the queue is full, one
        buffered event is discarded to make room for the sentinel.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(_SENTINEL)
        except asyncio.QueueFull:
            # Consumer is likely gone.  Drop one event to make room.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            try:
                self._queue.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE queue full for session %s, sentinel not delivered",
                    self._session_id,
                )

    async def event_generator(self) -> AsyncIterator[dict[str, str]]:
        """Yield SSE-formatted dicts for ``EventSourceResponse``.

        Each dict has ``id`` and ``data`` keys.  The ``data`` value is
        the JSON-serialized AG-UI event.  The generator exits after a
        terminal event or the sentinel is received.
        """
        while True:
            item = await self._queue.get()

            if item is _SENTINEL:
                break

            if not isinstance(item, BaseEvent):
                continue

            yield encode_sse(item)

            if is_terminal(item):
                break
