"""AG-UI protocol adapter -- converts SDK events to AG-UI events.

This is the default ``ProtocolAdapter`` implementation.  It produces
``ag_ui.core`` event instances directly, following the AG-UI specification.

Standard AG-UI events are used for content streaming (text, reasoning,
tool calls) and lifecycle (run started/finished/error).  Runtime extensions
(subagent, compact, steering, usage) are delivered via ``CustomEvent``.

All events -- including pipeline lifecycle (``PipelineStarted``,
``PipelineCompleted``, ``UsageSnapshot``) -- flow through ``on_event()``.
The adapter inspects the inner event type and produces the appropriate
AG-UI output.

The adapter is stateful: it tracks open text/reasoning/tool_call streams
to emit properly bracketed start/end events, and handles stream cleanup
on interrupt or error.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
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
from pydantic_ai import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
    ToolReturnPart,
)

from netherbrain.agent_runtime.execution.events import (
    PipelineCompleted,
    PipelineStarted,
    UsageSnapshot,
)
from netherbrain.agent_runtime.models.events import ExtensionEvent
from netherbrain.agent_runtime.streaming.protocols.base import ProtocolAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ToolCallResult status values
# ---------------------------------------------------------------------------

TOOL_STATUS_COMPLETE = "complete"
TOOL_STATUS_RETRY = "retry"
TOOL_STATUS_CANCEL = "cancel"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class AGUIProtocol(ProtocolAdapter):
    """Stateful AG-UI protocol adapter.

    Converts internal SDK ``StreamEvent`` instances to ``ag_ui.core``
    event objects.  Tracks open content streams to ensure proper
    bracketing (start/end pairs).

    All events flow through ``on_event()``::

        adapter = AGUIProtocol()

        async for sdk_event in streamer:
            async for evt in adapter.on_event(sdk_event):
                await transport.send(evt)
    """

    def __init__(self) -> None:
        # Identifiers (set when PipelineStarted arrives).
        self._session_id: str = ""
        self._conversation_id: str = ""

        # Stream state tracking.
        self._message_id: str = _new_id()
        self._reasoning_id: str = _new_id()
        self._text_open: bool = False
        self._reasoning_open: bool = False
        self._reasoning_msg_open: bool = False
        self._tool_call_ids: set[str] = set()

        # Event buffer for post-execution access.
        self._buffer: list[BaseEvent] = []

    @property
    def buffer(self) -> list[BaseEvent]:
        """All protocol events emitted during this session."""
        return self._buffer

    # ------------------------------------------------------------------
    # ProtocolAdapter interface
    # ------------------------------------------------------------------

    async def on_event(self, event: Any) -> AsyncIterator[BaseEvent]:
        """Convert a single SDK ``StreamEvent`` to AG-UI events."""
        # Unwrap StreamEvent wrapper.
        inner = getattr(event, "event", event)

        for evt in self._dispatch(inner):
            yield evt

    def _dispatch(self, inner: Any) -> list[BaseEvent]:
        """Route an unwrapped event to the appropriate handler."""
        # -- Pipeline lifecycle events -------------------------------------
        if isinstance(inner, PipelineStarted):
            return self._handle_pipeline_started(inner)

        if isinstance(inner, PipelineCompleted):
            return self._handle_pipeline_completed(inner)

        if isinstance(inner, UsageSnapshot):
            return self._handle_usage_snapshot(inner)

        # -- pydantic-ai streaming events ----------------------------------
        if isinstance(inner, PartStartEvent):
            return self._handle_part_start(inner)

        if isinstance(inner, PartDeltaEvent):
            return self._handle_part_delta(inner)

        if isinstance(inner, PartEndEvent):
            return self._handle_part_end(inner)

        # -- pydantic-ai tool lifecycle ------------------------------------
        if isinstance(inner, FunctionToolCallEvent):
            return []  # Already handled by PartStartEvent.

        if isinstance(inner, FunctionToolResultEvent):
            return self._handle_tool_result(inner)

        # -- SDK sideband events -------------------------------------------
        return self._handle_sideband(inner)

    async def on_error(self, *, code: str, message: str) -> AsyncIterator[BaseEvent]:
        """Close open streams, then emit ``RunErrorEvent``."""
        for evt in self._close_open_streams():
            yield evt
        yield self._emit(
            RunErrorEvent(
                message=message,
                code=code,
            )
        )

    # ------------------------------------------------------------------
    # Pipeline lifecycle handlers
    # ------------------------------------------------------------------

    def _handle_pipeline_started(self, event: PipelineStarted) -> list[BaseEvent]:
        self._session_id = event.session_id
        self._conversation_id = event.conversation_id
        return [
            self._emit(
                RunStartedEvent(
                    thread_id=event.conversation_id,
                    run_id=event.session_id,
                )
            )
        ]

    def _handle_pipeline_completed(self, event: PipelineCompleted) -> list[BaseEvent]:
        events = self._close_open_streams()
        events.append(
            self._emit(
                RunFinishedEvent(
                    thread_id=self._conversation_id,
                    run_id=self._session_id,
                )
            )
        )
        return events

    def _handle_usage_snapshot(self, event: UsageSnapshot) -> list[BaseEvent]:
        return [
            self._emit(
                CustomEvent(
                    name=ExtensionEvent.USAGE_SNAPSHOT,
                    value=asdict(event.usage),
                )
            )
        ]

    # ------------------------------------------------------------------
    # Part event handlers
    # ------------------------------------------------------------------

    def _handle_part_start(self, event: PartStartEvent) -> list[BaseEvent]:
        part = event.part
        events: list[BaseEvent] = []

        if isinstance(part, TextPart):
            self._text_open = True
            events.append(
                self._emit(
                    TextMessageStartEvent(
                        message_id=self._message_id,
                        role="assistant",
                    )
                )
            )
            if part.content:
                events.append(
                    self._emit(
                        TextMessageContentEvent(
                            message_id=self._message_id,
                            delta=part.content,
                        )
                    )
                )

        elif isinstance(part, ThinkingPart):
            self._reasoning_id = _new_id()
            self._reasoning_open = True
            events.append(
                self._emit(
                    ReasoningStartEvent(
                        message_id=self._reasoning_id,
                    )
                )
            )
            if part.content:
                self._reasoning_msg_open = True
                events.append(
                    self._emit(
                        ReasoningMessageStartEvent(
                            message_id=self._reasoning_id,
                            role="assistant",
                        )
                    )
                )
                events.append(
                    self._emit(
                        ReasoningMessageContentEvent(
                            message_id=self._reasoning_id,
                            delta=part.content,
                        )
                    )
                )

        elif isinstance(part, ToolCallPart):
            tool_call_id = part.tool_call_id
            self._tool_call_ids.add(tool_call_id)
            events.append(
                self._emit(
                    ToolCallStartEvent(
                        tool_call_id=tool_call_id,
                        tool_call_name=part.tool_name,
                        parent_message_id=self._message_id,
                    )
                )
            )
            if part.args:
                events.append(
                    self._emit(
                        ToolCallArgsEvent(
                            tool_call_id=tool_call_id,
                            delta=part.args_as_json_str(),
                        )
                    )
                )

        return events

    def _handle_part_delta(self, event: PartDeltaEvent) -> list[BaseEvent]:
        delta = event.delta

        if isinstance(delta, TextPartDelta):
            return self._handle_text_delta(delta)
        if isinstance(delta, ThinkingPartDelta):
            return self._handle_thinking_delta(delta)
        if isinstance(delta, ToolCallPartDelta):
            return self._handle_tool_call_delta(delta)
        return []

    def _handle_text_delta(self, delta: TextPartDelta) -> list[BaseEvent]:
        if not delta.content_delta:
            return []
        events: list[BaseEvent] = []
        if not self._text_open:
            # Late-arriving text delta without a PartStart.
            self._text_open = True
            events.append(
                self._emit(
                    TextMessageStartEvent(
                        message_id=self._message_id,
                        role="assistant",
                    )
                )
            )
        events.append(
            self._emit(
                TextMessageContentEvent(
                    message_id=self._message_id,
                    delta=delta.content_delta,
                )
            )
        )
        return events

    def _handle_thinking_delta(self, delta: ThinkingPartDelta) -> list[BaseEvent]:
        if not delta.content_delta:
            return []
        events: list[BaseEvent] = []
        if not self._reasoning_msg_open:
            self._reasoning_msg_open = True
            events.append(
                self._emit(
                    ReasoningMessageStartEvent(
                        message_id=self._reasoning_id,
                        role="assistant",
                    )
                )
            )
        events.append(
            self._emit(
                ReasoningMessageContentEvent(
                    message_id=self._reasoning_id,
                    delta=delta.content_delta,
                )
            )
        )
        return events

    def _handle_tool_call_delta(self, delta: ToolCallPartDelta) -> list[BaseEvent]:
        tool_call_id = delta.tool_call_id
        if tool_call_id not in self._tool_call_ids:
            return []
        args_delta = delta.args_delta
        if isinstance(args_delta, dict):
            args_delta = json.dumps(args_delta)
        if args_delta:
            return [
                self._emit(
                    ToolCallArgsEvent(
                        tool_call_id=tool_call_id,
                        delta=args_delta,
                    )
                )
            ]
        return []

    def _handle_part_end(self, event: PartEndEvent) -> list[BaseEvent]:
        part = event.part
        events: list[BaseEvent] = []

        if isinstance(part, TextPart):
            if self._text_open:
                events.append(
                    self._emit(
                        TextMessageEndEvent(
                            message_id=self._message_id,
                        )
                    )
                )
                self._text_open = False

        elif isinstance(part, ThinkingPart):
            if self._reasoning_msg_open:
                events.append(
                    self._emit(
                        ReasoningMessageEndEvent(
                            message_id=self._reasoning_id,
                        )
                    )
                )
                self._reasoning_msg_open = False
            if self._reasoning_open:
                events.append(
                    self._emit(
                        ReasoningEndEvent(
                            message_id=self._reasoning_id,
                        )
                    )
                )
                self._reasoning_open = False

        elif isinstance(part, ToolCallPart):
            tool_call_id = part.tool_call_id
            if tool_call_id in self._tool_call_ids:
                self._tool_call_ids.discard(tool_call_id)
                events.append(
                    self._emit(
                        ToolCallEndEvent(
                            tool_call_id=tool_call_id,
                        )
                    )
                )

        return events

    # ------------------------------------------------------------------
    # Tool result handler
    # ------------------------------------------------------------------

    def _handle_tool_result(self, event: FunctionToolResultEvent) -> list[BaseEvent]:
        result = event.result
        tool_call_id = result.tool_call_id

        if isinstance(result, ToolReturnPart):
            try:
                content = result.model_response_str()
            except Exception:
                content = str(result.content) if result.content else ""
            status = TOOL_STATUS_COMPLETE

        elif isinstance(result, RetryPromptPart):
            content = result.model_response()
            status = TOOL_STATUS_RETRY

        else:
            return []

        return [
            self._emit(
                ToolCallResultEvent(
                    message_id=self._message_id,
                    tool_call_id=tool_call_id,
                    content=content,
                    role="tool",
                    status=status,  # type: ignore[call-arg]  # extra field (BaseEvent allows extra)
                )
            )
        ]

    # ------------------------------------------------------------------
    # SDK sideband events
    # ------------------------------------------------------------------

    def _handle_sideband(self, event: Any) -> list[BaseEvent]:
        """Map SDK AgentEvent subclasses to AG-UI CustomEvents."""
        from ya_agent_sdk.events import (
            CompactCompleteEvent,
            CompactStartEvent,
            HandoffCompleteEvent,
            MessageReceivedEvent,
            SubagentCompleteEvent,
            SubagentStartEvent,
        )

        if isinstance(event, SubagentStartEvent):
            return [
                self._emit(
                    CustomEvent(
                        name=ExtensionEvent.SUBAGENT_STARTED,
                        value={
                            "sub_agent_id": event.agent_id,
                            "sub_agent_name": event.agent_name,
                            "prompt_preview": event.prompt_preview,
                        },
                    )
                )
            ]

        if isinstance(event, SubagentCompleteEvent):
            return [
                self._emit(
                    CustomEvent(
                        name=ExtensionEvent.SUBAGENT_COMPLETED,
                        value={
                            "sub_agent_id": event.agent_id,
                            "sub_agent_name": event.agent_name,
                            "success": event.success,
                            "result_preview": event.result_preview,
                            "error": event.error,
                            "duration_seconds": event.duration_seconds,
                        },
                    )
                )
            ]

        if isinstance(event, CompactStartEvent):
            return [
                self._emit(
                    CustomEvent(
                        name=ExtensionEvent.COMPACT_STARTED,
                        value={"message_count": event.message_count},
                    )
                )
            ]

        if isinstance(event, CompactCompleteEvent):
            return [
                self._emit(
                    CustomEvent(
                        name=ExtensionEvent.COMPACT_COMPLETED,
                        value={
                            "original_message_count": event.original_message_count,
                            "compacted_message_count": event.compacted_message_count,
                        },
                    )
                )
            ]

        if isinstance(event, HandoffCompleteEvent):
            return [
                self._emit(
                    CustomEvent(
                        name=ExtensionEvent.HANDOFF_COMPLETED,
                        value={"original_message_count": event.original_message_count},
                    )
                )
            ]

        if isinstance(event, MessageReceivedEvent):
            # Include message text so steering can be reconstructed from
            # persisted display_messages on history load.
            texts = [m.content_text for m in event.messages if m.content_text]
            return [
                self._emit(
                    CustomEvent(
                        name=ExtensionEvent.STEERING_RECEIVED,
                        value={
                            "message_count": len(event.messages),
                            "text": "\n".join(texts),
                        },
                    )
                )
            ]

        # Unknown event types are silently ignored.
        logger.debug("Ignoring SDK event: %s", type(event).__name__)
        return []

    # ------------------------------------------------------------------
    # Stream cleanup
    # ------------------------------------------------------------------

    def _close_open_streams(self) -> list[BaseEvent]:
        """Close any streams left open (e.g., after interrupt)."""
        events: list[BaseEvent] = []

        if self._text_open:
            events.append(
                self._emit(
                    TextMessageEndEvent(
                        message_id=self._message_id,
                    )
                )
            )
            self._text_open = False

        if self._reasoning_msg_open:
            events.append(
                self._emit(
                    ReasoningMessageEndEvent(
                        message_id=self._reasoning_id,
                    )
                )
            )
            self._reasoning_msg_open = False

        if self._reasoning_open:
            events.append(
                self._emit(
                    ReasoningEndEvent(
                        message_id=self._reasoning_id,
                    )
                )
            )
            self._reasoning_open = False

        for tool_call_id in list(self._tool_call_ids):
            events.append(
                self._emit(
                    ToolCallEndEvent(
                        tool_call_id=tool_call_id,
                    )
                )
            )
            events.append(
                self._emit(
                    ToolCallResultEvent(
                        message_id=self._message_id,
                        tool_call_id=tool_call_id,
                        content="",
                        role="tool",
                        status=TOOL_STATUS_CANCEL,  # type: ignore[call-arg]  # extra field
                    )
                )
            )
        self._tool_call_ids.clear()

        return events

    # ------------------------------------------------------------------
    # Per-message state reset
    # ------------------------------------------------------------------

    def reset_for_new_message(self) -> None:
        """Reset per-message state for the next model response.

        Called between model request loops when the model produces
        multiple response parts across turns.
        """
        self._message_id = _new_id()
        self._text_open = False
        self._reasoning_open = False
        self._reasoning_msg_open = False
        # Tool call IDs persist across turns until PartEndEvent.

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, event: BaseEvent) -> BaseEvent:
        self._buffer.append(event)
        return event
