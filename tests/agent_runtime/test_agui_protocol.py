"""Unit tests for AGUIProtocol adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
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
from ya_agent_sdk.context import StreamEvent

from netherbrain.agent_runtime.execution.events import (
    MAIN_AGENT_ID,
    ModelUsage,
    PipelineCompleted,
    PipelineStarted,
    PipelineUsage,
    UsageSnapshot,
)
from netherbrain.agent_runtime.models.events import ExtensionEvent
from netherbrain.agent_runtime.streaming.protocols.agui import (
    TOOL_STATUS_CANCEL,
    TOOL_STATUS_COMPLETE,
    TOOL_STATUS_RETRY,
    AGUIProtocol,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wrap(event: Any) -> StreamEvent:
    """Wrap an inner event in a StreamEvent."""
    return StreamEvent(
        agent_id=MAIN_AGENT_ID,
        agent_name=MAIN_AGENT_ID,
        event=event,
    )


async def _collect(adapter: AGUIProtocol, event: Any) -> list[BaseEvent]:
    """Send a StreamEvent through the adapter and collect results."""
    results: list[BaseEvent] = []
    async for evt in adapter.on_event(_wrap(event)):
        results.append(evt)
    return results


async def _collect_error(adapter: AGUIProtocol, *, code: str, message: str) -> list[BaseEvent]:
    """Send an error through the adapter and collect results."""
    results: list[BaseEvent] = []
    async for evt in adapter.on_error(code=code, message=message):
        results.append(evt)
    return results


def _new_adapter(session_id: str = "sess-1", conversation_id: str = "conv-1") -> AGUIProtocol:
    """Create an adapter pre-initialized with session info."""
    adapter = AGUIProtocol()
    # Pre-set identifiers (normally set by PipelineStarted).
    adapter._session_id = session_id
    adapter._conversation_id = conversation_id
    return adapter


# ---------------------------------------------------------------------------
# Pipeline lifecycle events
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pipeline_started_emits_run_started() -> None:
    adapter = AGUIProtocol()
    events = await _collect(
        adapter,
        PipelineStarted(
            event_id="sess-1",
            session_id="sess-1",
            conversation_id="conv-1",
        ),
    )

    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, RunStartedEvent)
    assert evt.type == EventType.RUN_STARTED
    assert evt.run_id == "sess-1"
    assert evt.thread_id == "conv-1"

    # Verify identifiers are stored.
    assert adapter._session_id == "sess-1"
    assert adapter._conversation_id == "conv-1"


@pytest.mark.anyio
async def test_pipeline_completed_emits_run_finished() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PipelineCompleted(
            event_id="sess-1",
            session_id="sess-1",
            reply="Hello!",
        ),
    )

    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, RunFinishedEvent)
    assert evt.type == EventType.RUN_FINISHED
    assert evt.run_id == "sess-1"
    assert evt.thread_id == "conv-1"


@pytest.mark.anyio
async def test_pipeline_completed_closes_open_streams() -> None:
    adapter = _new_adapter()

    # Open a text stream.
    await _collect(adapter, PartStartEvent(index=0, part=TextPart("hi")))
    assert adapter._text_open

    # PipelineCompleted should close it.
    events = await _collect(
        adapter,
        PipelineCompleted(
            event_id="sess-1",
            session_id="sess-1",
        ),
    )

    # TextMessageEnd + RunFinished.
    types = [type(e) for e in events]
    assert TextMessageEndEvent in types
    assert RunFinishedEvent in types
    assert not adapter._text_open


@pytest.mark.anyio
async def test_usage_snapshot_emits_custom_event() -> None:
    adapter = _new_adapter()
    usage = PipelineUsage()
    usage.add(
        "anthropic:claude-sonnet-4",
        ModelUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=10,
            cache_write_tokens=5,
            reasoning_tokens=0,
            total_tokens=150,
            requests=3,
        ),
    )
    events = await _collect(
        adapter,
        UsageSnapshot(
            event_id="sess-1",
            session_id="sess-1",
            usage=usage,
        ),
    )

    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, CustomEvent)
    assert evt.name == ExtensionEvent.USAGE_SNAPSHOT
    model_usages = evt.value["model_usages"]
    assert "anthropic:claude-sonnet-4" in model_usages
    model = model_usages["anthropic:claude-sonnet-4"]
    assert model["input_tokens"] == 100
    assert model["output_tokens"] == 50
    assert model["cache_read_tokens"] == 10
    assert model["cache_write_tokens"] == 5
    assert model["total_tokens"] == 150
    assert model["requests"] == 3


# ---------------------------------------------------------------------------
# Text streaming
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_text_part_start() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=TextPart("Hello"),
        ),
    )

    assert len(events) == 2
    assert isinstance(events[0], TextMessageStartEvent)
    assert events[0].role == "assistant"
    assert isinstance(events[1], TextMessageContentEvent)
    assert events[1].delta == "Hello"
    assert adapter._text_open


@pytest.mark.anyio
async def test_text_part_start_empty_content() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=TextPart(""),
        ),
    )

    assert len(events) == 1
    assert isinstance(events[0], TextMessageStartEvent)


@pytest.mark.anyio
async def test_text_part_delta() -> None:
    adapter = _new_adapter()
    # Open text stream first.
    await _collect(adapter, PartStartEvent(index=0, part=TextPart("")))

    events = await _collect(
        adapter,
        PartDeltaEvent(
            index=0,
            delta=TextPartDelta(" world"),
        ),
    )

    assert len(events) == 1
    assert isinstance(events[0], TextMessageContentEvent)
    assert events[0].delta == " world"


@pytest.mark.anyio
async def test_text_delta_empty_ignored() -> None:
    adapter = _new_adapter()
    await _collect(adapter, PartStartEvent(index=0, part=TextPart("")))

    events = await _collect(
        adapter,
        PartDeltaEvent(
            index=0,
            delta=TextPartDelta(""),
        ),
    )

    assert len(events) == 0


@pytest.mark.anyio
async def test_text_delta_late_arrival_opens_stream() -> None:
    adapter = _new_adapter()
    # No PartStart -- delta arrives directly.
    events = await _collect(
        adapter,
        PartDeltaEvent(
            index=0,
            delta=TextPartDelta("hello"),
        ),
    )

    assert len(events) == 2
    assert isinstance(events[0], TextMessageStartEvent)
    assert isinstance(events[1], TextMessageContentEvent)
    assert adapter._text_open


@pytest.mark.anyio
async def test_text_part_end() -> None:
    adapter = _new_adapter()
    await _collect(adapter, PartStartEvent(index=0, part=TextPart("")))
    assert adapter._text_open

    events = await _collect(
        adapter,
        PartEndEvent(
            index=0,
            part=TextPart("done"),
        ),
    )

    assert len(events) == 1
    assert isinstance(events[0], TextMessageEndEvent)
    assert not adapter._text_open


# ---------------------------------------------------------------------------
# Reasoning streaming
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_thinking_part_start_with_content() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ThinkingPart("Let me think..."),
        ),
    )

    assert len(events) == 3
    assert isinstance(events[0], ReasoningStartEvent)
    assert isinstance(events[1], ReasoningMessageStartEvent)
    assert events[1].role == "assistant"
    assert isinstance(events[2], ReasoningMessageContentEvent)
    assert events[2].delta == "Let me think..."
    assert adapter._reasoning_open
    assert adapter._reasoning_msg_open


@pytest.mark.anyio
async def test_thinking_part_start_empty() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ThinkingPart(""),
        ),
    )

    assert len(events) == 1
    assert isinstance(events[0], ReasoningStartEvent)
    assert adapter._reasoning_open
    assert not adapter._reasoning_msg_open


@pytest.mark.anyio
async def test_thinking_delta_opens_reasoning_message() -> None:
    adapter = _new_adapter()
    # Start reasoning without content.
    await _collect(adapter, PartStartEvent(index=0, part=ThinkingPart("")))
    assert not adapter._reasoning_msg_open

    # Delta should open reasoning message.
    events = await _collect(
        adapter,
        PartDeltaEvent(
            index=0,
            delta=ThinkingPartDelta(content_delta="step 1"),
        ),
    )

    assert len(events) == 2
    assert isinstance(events[0], ReasoningMessageStartEvent)
    assert isinstance(events[1], ReasoningMessageContentEvent)
    assert events[1].delta == "step 1"
    assert adapter._reasoning_msg_open


@pytest.mark.anyio
async def test_thinking_part_end() -> None:
    adapter = _new_adapter()
    await _collect(adapter, PartStartEvent(index=0, part=ThinkingPart("ok")))

    events = await _collect(
        adapter,
        PartEndEvent(
            index=0,
            part=ThinkingPart("ok"),
        ),
    )

    # Should close both reasoning message and reasoning block.
    types = [type(e) for e in events]
    assert ReasoningMessageEndEvent in types
    assert ReasoningEndEvent in types
    assert not adapter._reasoning_open
    assert not adapter._reasoning_msg_open


# ---------------------------------------------------------------------------
# Tool call streaming
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tool_call_start() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ToolCallPart("shell", '{"cmd": "ls"}', tool_call_id="tc-1"),
        ),
    )

    assert len(events) == 2
    assert isinstance(events[0], ToolCallStartEvent)
    assert events[0].tool_call_id == "tc-1"
    assert events[0].tool_call_name == "shell"
    assert isinstance(events[1], ToolCallArgsEvent)
    assert "cmd" in events[1].delta
    assert "tc-1" in adapter._tool_call_ids


@pytest.mark.anyio
async def test_tool_call_start_no_args() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ToolCallPart("read_file", tool_call_id="tc-2"),
        ),
    )

    assert len(events) == 1
    assert isinstance(events[0], ToolCallStartEvent)


@pytest.mark.anyio
async def test_tool_call_delta() -> None:
    adapter = _new_adapter()
    await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ToolCallPart("shell", tool_call_id="tc-1"),
        ),
    )

    events = await _collect(
        adapter,
        PartDeltaEvent(
            index=0,
            delta=ToolCallPartDelta(args_delta='{"path":', tool_call_id="tc-1"),
        ),
    )

    assert len(events) == 1
    assert isinstance(events[0], ToolCallArgsEvent)
    assert events[0].tool_call_id == "tc-1"
    assert events[0].delta == '{"path":'


@pytest.mark.anyio
async def test_tool_call_delta_dict_args() -> None:
    adapter = _new_adapter()
    await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ToolCallPart("shell", tool_call_id="tc-1"),
        ),
    )

    events = await _collect(
        adapter,
        PartDeltaEvent(
            index=0,
            delta=ToolCallPartDelta(args_delta={"key": "val"}, tool_call_id="tc-1"),
        ),
    )

    assert len(events) == 1
    assert '"key"' in events[0].delta


@pytest.mark.anyio
async def test_tool_call_delta_unknown_id_ignored() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        PartDeltaEvent(
            index=0,
            delta=ToolCallPartDelta(args_delta='"x"', tool_call_id="unknown"),
        ),
    )

    assert len(events) == 0


@pytest.mark.anyio
async def test_tool_call_end() -> None:
    adapter = _new_adapter()
    await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ToolCallPart("shell", tool_call_id="tc-1"),
        ),
    )

    events = await _collect(
        adapter,
        PartEndEvent(
            index=0,
            part=ToolCallPart("shell", tool_call_id="tc-1"),
        ),
    )

    assert len(events) == 1
    assert isinstance(events[0], ToolCallEndEvent)
    assert events[0].tool_call_id == "tc-1"
    assert "tc-1" not in adapter._tool_call_ids


# ---------------------------------------------------------------------------
# Tool results with status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tool_result_complete() -> None:
    adapter = _new_adapter()
    result = ToolReturnPart(
        tool_name="shell",
        content="file1.txt\nfile2.txt",
        tool_call_id="tc-1",
    )
    events = await _collect(adapter, FunctionToolResultEvent(result=result))

    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, ToolCallResultEvent)
    assert evt.tool_call_id == "tc-1"
    assert evt.role == "tool"
    # Check extra status field.
    dumped = evt.model_dump(by_alias=True, exclude_none=True)
    assert dumped["status"] == TOOL_STATUS_COMPLETE


@pytest.mark.anyio
async def test_tool_result_retry() -> None:
    adapter = _new_adapter()
    result = RetryPromptPart(
        content="Please provide a valid path",
        tool_name="read_file",
        tool_call_id="tc-2",
    )
    events = await _collect(adapter, FunctionToolResultEvent(result=result))

    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, ToolCallResultEvent)
    dumped = evt.model_dump(by_alias=True, exclude_none=True)
    assert dumped["status"] == TOOL_STATUS_RETRY


# ---------------------------------------------------------------------------
# Sideband events
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_subagent_started_custom_event() -> None:
    from ya_agent_sdk.events import SubagentStartEvent

    adapter = _new_adapter()
    events = await _collect(
        adapter,
        SubagentStartEvent(
            event_id="e1",
            agent_id="sub-1",
            agent_name="helper",
            prompt_preview="do something",
        ),
    )

    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, CustomEvent)
    assert evt.name == ExtensionEvent.SUBAGENT_STARTED
    assert evt.value["sub_agent_id"] == "sub-1"
    assert evt.value["sub_agent_name"] == "helper"


@pytest.mark.anyio
async def test_compact_events() -> None:
    from ya_agent_sdk.events import CompactCompleteEvent, CompactStartEvent

    adapter = _new_adapter()

    start_events = await _collect(
        adapter,
        CompactStartEvent(
            event_id="e1",
            message_count=20,
        ),
    )
    assert len(start_events) == 1
    assert isinstance(start_events[0], CustomEvent)
    assert start_events[0].name == ExtensionEvent.COMPACT_STARTED
    assert start_events[0].value["message_count"] == 20

    end_events = await _collect(
        adapter,
        CompactCompleteEvent(
            event_id="e1",
            original_message_count=20,
            compacted_message_count=5,
        ),
    )
    assert len(end_events) == 1
    assert isinstance(end_events[0], CustomEvent)
    assert end_events[0].name == ExtensionEvent.COMPACT_COMPLETED
    assert end_events[0].value["original_message_count"] == 20
    assert end_events[0].value["compacted_message_count"] == 5


@pytest.mark.anyio
async def test_unknown_event_ignored() -> None:
    @dataclass
    class UnknownEvent:
        event_id: str = "x"

    adapter = _new_adapter()
    events = await _collect(adapter, UnknownEvent())

    assert len(events) == 0


@pytest.mark.anyio
async def test_function_tool_call_event_ignored() -> None:
    adapter = _new_adapter()
    events = await _collect(
        adapter,
        FunctionToolCallEvent(
            part=MagicMock(),
        ),
    )

    assert len(events) == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_on_error_emits_run_error() -> None:
    adapter = _new_adapter()
    events = await _collect_error(adapter, code="test_error", message="Something broke")

    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, RunErrorEvent)
    assert evt.type == EventType.RUN_ERROR
    assert evt.code == "test_error"
    assert evt.message == "Something broke"


@pytest.mark.anyio
async def test_on_error_closes_open_text_stream() -> None:
    adapter = _new_adapter()
    await _collect(adapter, PartStartEvent(index=0, part=TextPart("start")))
    assert adapter._text_open

    events = await _collect_error(adapter, code="err", message="fail")

    types = [type(e) for e in events]
    assert TextMessageEndEvent in types
    assert RunErrorEvent in types
    assert not adapter._text_open


@pytest.mark.anyio
async def test_on_error_closes_open_tool_calls() -> None:
    adapter = _new_adapter()
    await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ToolCallPart("shell", tool_call_id="tc-1"),
        ),
    )
    assert "tc-1" in adapter._tool_call_ids

    events = await _collect_error(adapter, code="err", message="fail")

    types = [type(e) for e in events]
    assert ToolCallEndEvent in types
    assert ToolCallResultEvent in types
    assert RunErrorEvent in types
    assert len(adapter._tool_call_ids) == 0

    # Verify cancelled tool result has cancel status.
    tool_results = [e for e in events if isinstance(e, ToolCallResultEvent)]
    assert len(tool_results) == 1
    dumped = tool_results[0].model_dump(by_alias=True, exclude_none=True)
    assert dumped["status"] == TOOL_STATUS_CANCEL


@pytest.mark.anyio
async def test_on_error_closes_open_reasoning() -> None:
    adapter = _new_adapter()
    await _collect(
        adapter,
        PartStartEvent(
            index=0,
            part=ThinkingPart("thinking..."),
        ),
    )
    assert adapter._reasoning_open
    assert adapter._reasoning_msg_open

    events = await _collect_error(adapter, code="err", message="fail")

    types = [type(e) for e in events]
    assert ReasoningMessageEndEvent in types
    assert ReasoningEndEvent in types
    assert RunErrorEvent in types


# ---------------------------------------------------------------------------
# Buffer tracking
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_buffer_captures_all_events() -> None:
    adapter = AGUIProtocol()

    # Pipeline start.
    await _collect(
        adapter,
        PipelineStarted(
            event_id="s1",
            session_id="s1",
            conversation_id="c1",
        ),
    )
    # Text.
    await _collect(adapter, PartStartEvent(index=0, part=TextPart("hi")))
    await _collect(adapter, PartEndEvent(index=0, part=TextPart("hi")))
    # Complete.
    await _collect(adapter, PipelineCompleted(event_id="s1", session_id="s1"))

    # Buffer should have: RunStarted, TextMsgStart, TextMsgContent, TextMsgEnd, RunFinished.
    assert len(adapter.buffer) == 5
    assert isinstance(adapter.buffer[0], RunStartedEvent)
    assert isinstance(adapter.buffer[-1], RunFinishedEvent)


# ---------------------------------------------------------------------------
# Full lifecycle integration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_full_text_lifecycle() -> None:
    """Complete text streaming lifecycle: start -> content -> end."""
    adapter = AGUIProtocol()
    all_events: list[BaseEvent] = []

    # Pipeline start.
    all_events.extend(
        await _collect(
            adapter,
            PipelineStarted(
                event_id="s1",
                session_id="s1",
                conversation_id="c1",
            ),
        )
    )

    # Text stream.
    all_events.extend(
        await _collect(
            adapter,
            PartStartEvent(
                index=0,
                part=TextPart(""),
            ),
        )
    )
    all_events.extend(
        await _collect(
            adapter,
            PartDeltaEvent(
                index=0,
                delta=TextPartDelta("Hello "),
            ),
        )
    )
    all_events.extend(
        await _collect(
            adapter,
            PartDeltaEvent(
                index=0,
                delta=TextPartDelta("world!"),
            ),
        )
    )
    all_events.extend(
        await _collect(
            adapter,
            PartEndEvent(
                index=0,
                part=TextPart("Hello world!"),
            ),
        )
    )

    # Pipeline complete.
    all_events.extend(
        await _collect(
            adapter,
            PipelineCompleted(
                event_id="s1",
                session_id="s1",
                reply="Hello world!",
            ),
        )
    )

    types = [type(e) for e in all_events]
    assert types == [
        RunStartedEvent,
        TextMessageStartEvent,
        TextMessageContentEvent,
        TextMessageContentEvent,
        TextMessageEndEvent,
        RunFinishedEvent,
    ]


@pytest.mark.anyio
async def test_full_tool_lifecycle() -> None:
    """Complete tool call lifecycle: start -> args -> end -> result."""
    adapter = _new_adapter()
    all_events: list[BaseEvent] = []

    # Tool call.
    all_events.extend(
        await _collect(
            adapter,
            PartStartEvent(
                index=0,
                part=ToolCallPart("shell", tool_call_id="tc-1"),
            ),
        )
    )
    all_events.extend(
        await _collect(
            adapter,
            PartDeltaEvent(
                index=0,
                delta=ToolCallPartDelta(args_delta='{"cmd":"ls"}', tool_call_id="tc-1"),
            ),
        )
    )
    all_events.extend(
        await _collect(
            adapter,
            PartEndEvent(
                index=0,
                part=ToolCallPart("shell", '{"cmd":"ls"}', tool_call_id="tc-1"),
            ),
        )
    )

    # Tool result.
    all_events.extend(
        await _collect(
            adapter,
            FunctionToolResultEvent(
                result=ToolReturnPart(
                    tool_name="shell",
                    content="file1.txt",
                    tool_call_id="tc-1",
                ),
            ),
        )
    )

    types = [type(e) for e in all_events]
    assert types == [
        ToolCallStartEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
        ToolCallResultEvent,
    ]

    # Verify status.
    result_evt = all_events[-1]
    assert isinstance(result_evt, ToolCallResultEvent)
    dumped = result_evt.model_dump(by_alias=True, exclude_none=True)
    assert dumped["status"] == TOOL_STATUS_COMPLETE


@pytest.mark.anyio
async def test_reset_for_new_message() -> None:
    adapter = _new_adapter()

    # Open text stream.
    await _collect(adapter, PartStartEvent(index=0, part=TextPart("hi")))
    await _collect(adapter, PartEndEvent(index=0, part=TextPart("hi")))

    old_message_id = adapter._message_id
    adapter.reset_for_new_message()

    assert adapter._message_id != old_message_id
    assert not adapter._text_open
    assert not adapter._reasoning_open
    assert not adapter._reasoning_msg_open
