"""AG-UI protocol event types and helpers.

This module re-exports event types from ``ag_ui.core`` and provides
runtime extension event names via ``CustomEvent``.

Standard AG-UI events:
    Lifecycle (RunStarted/Finished/Error), text messages, reasoning,
    tool calls -- all come from ``ag_ui.core``.

Runtime extensions:
    Subagent, compact, handoff, steering, usage -- delivered as
    ``ag_ui.core.CustomEvent`` with a descriptive ``name`` field.

Transport helpers:
    ``is_terminal()``, ``encode_sse()``, ``TERMINAL_TYPES``.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

# ---------------------------------------------------------------------------
# Re-exports (for convenient single-source imports)
# ---------------------------------------------------------------------------

__all__ = [
    # Helpers
    "TERMINAL_TYPES",
    # AG-UI core
    "BaseEvent",
    "CustomEvent",
    "EventType",
    "ExtensionEvent",
    "ReasoningEndEvent",
    "ReasoningMessageContentEvent",
    "ReasoningMessageEndEvent",
    "ReasoningMessageStartEvent",
    "ReasoningStartEvent",
    "RunErrorEvent",
    "RunFinishedEvent",
    "RunStartedEvent",
    "TextMessageContentEvent",
    "TextMessageEndEvent",
    "TextMessageStartEvent",
    "ToolCallArgsEvent",
    "ToolCallEndEvent",
    "ToolCallResultEvent",
    "ToolCallStartEvent",
    "encode_sse",
    "event_id",
    "is_terminal",
]

# ---------------------------------------------------------------------------
# Extension event names (delivered via CustomEvent)
# ---------------------------------------------------------------------------


class ExtensionEvent(StrEnum):
    """Names for runtime extension events (CustomEvent.name)."""

    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    COMPACT_STARTED = "compact_started"
    COMPACT_COMPLETED = "compact_completed"
    HANDOFF_COMPLETED = "handoff_completed"
    STEERING_RECEIVED = "steering_received"
    USAGE_SNAPSHOT = "usage_snapshot"


# ---------------------------------------------------------------------------
# Terminal event detection
# ---------------------------------------------------------------------------

TERMINAL_TYPES: frozenset[EventType] = frozenset({
    EventType.RUN_FINISHED,
    EventType.RUN_ERROR,
})


def is_terminal(event: BaseEvent) -> bool:
    """Check if an event is terminal (no further events expected)."""
    return event.type in TERMINAL_TYPES


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def event_id() -> str:
    """Generate a short unique event ID for SSE ``id:`` field."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# SSE encoding
# ---------------------------------------------------------------------------


def encode_sse(evt: BaseEvent, *, sse_id: str | None = None) -> dict[str, str]:
    """Format an AG-UI event for sse-starlette.

    Returns a dict with ``id`` and ``data`` keys.  The ``data`` value
    is the JSON-serialized AG-UI event (camelCase, no nulls).

    The ``id`` field enables reconnection via ``Last-Event-ID``.
    """
    return {
        "id": sse_id or event_id(),
        "data": evt.model_dump_json(by_alias=True, exclude_none=True),
    }
