"""Protocol adapter interface -- the sole coupling point between internal and external events.

A ``ProtocolAdapter`` converts the internal event stream (SDK ``StreamEvent``
plus pipeline lifecycle events) into AG-UI protocol events (``ag_ui.core.BaseEvent``).

All events -- SDK streaming events, sideband events, and pipeline lifecycle
events (``PipelineStarted``, ``PipelineCompleted``, ``UsageSnapshot``) -- flow
through the same ``on_event()`` method.  The adapter determines the type of
each event and produces the appropriate AG-UI output.

The coordinator injects pipeline lifecycle events into the ``StreamEvent``
stream so that the adapter sees a single unified event flow::

    async for sdk_event in streamer:
        async for evt in adapter.on_event(sdk_event):
            await transport.send(evt)

The only separate path is ``on_error()``, which handles execution failures
from the except block where no StreamEvent can be injected.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ag_ui.core import BaseEvent
    from ya_agent_sdk.context import StreamEvent


class ProtocolAdapter(abc.ABC):
    """Abstract interface for converting internal events to protocol events.

    Each method is an async generator yielding zero or more
    ``ag_ui.core.BaseEvent`` instances.  The coordinator iterates the
    generator and delivers each event to the transport.
    """

    @abc.abstractmethod
    async def on_event(self, event: StreamEvent) -> AsyncIterator[BaseEvent]:
        """Yield protocol events for a single ``StreamEvent``.

        Handles all event types:
        - SDK streaming events (PartStart, PartDelta, PartEnd, etc.)
        - SDK sideband events (Subagent, Compact, Handoff, etc.)
        - Pipeline lifecycle events (PipelineStarted, PipelineCompleted,
          UsageSnapshot) injected by the coordinator

        May yield zero events (for ignored SDK events) or multiple
        (e.g., a PartStartEvent that opens a stream and emits initial content).
        """
        yield  # type: ignore[misc]  # abstract async generator

    @abc.abstractmethod
    async def on_error(self, *, code: str, message: str) -> AsyncIterator[BaseEvent]:
        """Yield protocol events for execution failure.

        Called when execution fails or is interrupted.  This is a separate
        path because errors originate from the except block where no
        ``StreamEvent`` can be injected into the stream.

        Implementations should close any open streams before emitting
        the terminal error event.
        """
        yield  # type: ignore[misc]  # abstract async generator
