"""Compress AG-UI event buffer into chunk events for persistent storage.

Collapses streaming triplets (Start + Content* + End) into single chunk
events that capture the full content.  Atomic events (ToolCallResult,
CustomEvent) are kept as-is.  Cumulative snapshot events (e.g.
usage_snapshot) are deduplicated -- only the last occurrence is kept.
Lifecycle events (RunStarted, RunFinished, etc.) are dropped since they
can be derived from the session index.

The output is a list of serialised AG-UI event dicts (camelCase keys),
suitable for writing to ``display_messages.json`` in the state store.
"""

from __future__ import annotations

import json
from typing import Literal

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    ReasoningEndEvent,
    ReasoningMessageChunkEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageChunkEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallChunkEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from netherbrain.agent_runtime.models.events import ExtensionEvent
from netherbrain.agent_runtime.store.base import DisplayMessages

# Event types to drop entirely (derivable from session index).
_DROP_TYPES = (RunStartedEvent, RunFinishedEvent, RunErrorEvent)

# CustomEvent names that are cumulative snapshots -- only the last one is kept.
_SNAPSHOT_NAMES = frozenset({ExtensionEvent.USAGE_SNAPSHOT})


def compress_display_messages(buffer: list[BaseEvent]) -> DisplayMessages:
    """Compress a full AG-UI event buffer into chunk events.

    Returns a list of dicts ready for JSON serialisation.
    """
    compressor = _Compressor()
    for event in buffer:
        compressor.process(event)
    return compressor.finish()


class _Compressor:
    """Stateful event compressor that accumulates streaming triplets."""

    def __init__(self) -> None:
        self._result: list[BaseEvent] = []
        self._text: _TextAcc | None = None
        self._tools: dict[str, _ToolAcc] = {}
        self._reasoning: _ReasoningAcc | None = None
        self._snapshots: dict[str, BaseEvent] = {}  # name -> last event

    def process(self, event: BaseEvent) -> None:
        """Process a single event."""
        if isinstance(event, _DROP_TYPES):
            return

        if isinstance(event, (TextMessageStartEvent, TextMessageContentEvent, TextMessageEndEvent)):
            self._handle_text(event)
        elif isinstance(event, (ToolCallStartEvent, ToolCallArgsEvent, ToolCallEndEvent)):
            self._handle_tool(event)
        elif isinstance(
            event,
            (
                ReasoningStartEvent,
                ReasoningMessageStartEvent,
                ReasoningMessageContentEvent,
                ReasoningMessageEndEvent,
                ReasoningEndEvent,
            ),
        ):
            self._handle_reasoning(event)
        elif isinstance(event, ToolCallResultEvent):
            self._result.append(event)
        elif isinstance(event, CustomEvent):
            if event.name in _SNAPSHOT_NAMES:
                self._snapshots[event.name] = event
            else:
                self._result.append(event)

    def finish(self) -> DisplayMessages:
        """Flush unclosed accumulators and serialise to dicts."""
        self._flush_unclosed()
        # Append retained snapshots (only the last of each kind).
        self._result.extend(self._snapshots.values())
        return [json.loads(evt.model_dump_json(by_alias=True, exclude_none=True)) for evt in self._result]

    # -- Text handlers ---------------------------------------------------------

    def _handle_text(self, event: BaseEvent) -> None:
        if isinstance(event, TextMessageStartEvent):
            self._text = _TextAcc(message_id=event.message_id, role=event.role)
        elif isinstance(event, TextMessageContentEvent):
            if self._text is not None:
                self._text.delta += event.delta
        elif isinstance(event, TextMessageEndEvent) and self._text is not None:
            self._result.append(
                TextMessageChunkEvent(
                    message_id=self._text.message_id,
                    role=self._text.role,
                    delta=self._text.delta,
                )
            )
            self._text = None

    # -- Tool handlers ---------------------------------------------------------

    def _handle_tool(self, event: BaseEvent) -> None:
        if isinstance(event, ToolCallStartEvent):
            self._tools[event.tool_call_id] = _ToolAcc(
                tool_call_id=event.tool_call_id,
                tool_call_name=event.tool_call_name,
                parent_message_id=event.parent_message_id,
            )
        elif isinstance(event, ToolCallArgsEvent):
            acc = self._tools.get(event.tool_call_id)
            if acc is not None:
                acc.delta += event.delta
        elif isinstance(event, ToolCallEndEvent):
            acc = self._tools.pop(event.tool_call_id, None)
            if acc is not None:
                self._result.append(
                    ToolCallChunkEvent(
                        tool_call_id=acc.tool_call_id,
                        tool_call_name=acc.tool_call_name,
                        parent_message_id=acc.parent_message_id,
                        delta=acc.delta,
                    )
                )

    # -- Reasoning handlers ----------------------------------------------------

    def _handle_reasoning(self, event: BaseEvent) -> None:
        if isinstance(event, ReasoningStartEvent):
            self._reasoning = _ReasoningAcc(message_id=event.message_id)
        elif isinstance(event, ReasoningMessageStartEvent):
            if self._reasoning is not None:
                self._reasoning.message_id = event.message_id
        elif isinstance(event, ReasoningMessageContentEvent):
            if self._reasoning is not None:
                self._reasoning.delta += event.delta
        elif isinstance(event, ReasoningMessageEndEvent):
            pass  # Wait for ReasoningEnd to emit chunk.
        elif isinstance(event, ReasoningEndEvent) and self._reasoning is not None and self._reasoning.delta:
            self._result.append(
                ReasoningMessageChunkEvent(
                    message_id=self._reasoning.message_id,
                    delta=self._reasoning.delta,
                )
            )
            self._reasoning = None

    # -- Flush -----------------------------------------------------------------

    def _flush_unclosed(self) -> None:
        """Flush any open accumulators (e.g., interrupted sessions)."""
        if self._text is not None and self._text.delta:
            self._result.append(
                TextMessageChunkEvent(
                    message_id=self._text.message_id,
                    role=self._text.role,
                    delta=self._text.delta,
                )
            )

        for acc in self._tools.values():
            self._result.append(
                ToolCallChunkEvent(
                    tool_call_id=acc.tool_call_id,
                    tool_call_name=acc.tool_call_name,
                    parent_message_id=acc.parent_message_id,
                    delta=acc.delta,
                )
            )

        if self._reasoning is not None and self._reasoning.delta:
            self._result.append(
                ReasoningMessageChunkEvent(
                    message_id=self._reasoning.message_id,
                    delta=self._reasoning.delta,
                )
            )


# -- Internal accumulators ---------------------------------------------------


# Type alias matching ag_ui.core's TextMessageRole.
_TextRole = Literal["developer", "system", "assistant", "user"]


class _TextAcc:
    __slots__ = ("delta", "message_id", "role")

    def __init__(self, message_id: str, role: _TextRole) -> None:
        self.message_id = message_id
        self.role: _TextRole = role
        self.delta = ""


class _ToolAcc:
    __slots__ = ("delta", "parent_message_id", "tool_call_id", "tool_call_name")

    def __init__(
        self,
        tool_call_id: str,
        tool_call_name: str,
        parent_message_id: str | None = None,
    ) -> None:
        self.tool_call_id = tool_call_id
        self.tool_call_name = tool_call_name
        self.parent_message_id = parent_message_id
        self.delta = ""


class _ReasoningAcc:
    __slots__ = ("delta", "message_id")

    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        self.delta = ""
