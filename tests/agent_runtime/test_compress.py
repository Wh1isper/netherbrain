"""Unit tests for display messages compression.

Tests the compress_display_messages() function that collapses AG-UI
streaming triplets (Start + Content* + End) into chunk events.
"""

from __future__ import annotations

from ag_ui.core import (
    CustomEvent,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
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

from netherbrain.agent_runtime.streaming.compress import compress_display_messages


def test_compress_text_message() -> None:
    """Text Start + Content* + End -> single TextMessageChunk."""
    buffer = [
        RunStartedEvent(thread_id="t1", run_id="r1"),
        TextMessageStartEvent(message_id="m1", role="assistant"),
        TextMessageContentEvent(message_id="m1", delta="Hello "),
        TextMessageContentEvent(message_id="m1", delta="world"),
        TextMessageEndEvent(message_id="m1"),
        RunFinishedEvent(thread_id="t1", run_id="r1"),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 1
    chunk = result[0]
    assert chunk["type"] == "TEXT_MESSAGE_CHUNK"
    assert chunk["messageId"] == "m1"
    assert chunk["role"] == "assistant"
    assert chunk["delta"] == "Hello world"


def test_compress_tool_call() -> None:
    """ToolCall Start + Args* + End -> single ToolCallChunk."""
    buffer = [
        ToolCallStartEvent(
            tool_call_id="tc1",
            tool_call_name="search",
            parent_message_id="m1",
        ),
        ToolCallArgsEvent(tool_call_id="tc1", delta='{"q":'),
        ToolCallArgsEvent(tool_call_id="tc1", delta='"test"}'),
        ToolCallEndEvent(tool_call_id="tc1"),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 1
    chunk = result[0]
    assert chunk["type"] == "TOOL_CALL_CHUNK"
    assert chunk["toolCallId"] == "tc1"
    assert chunk["toolCallName"] == "search"
    assert chunk["parentMessageId"] == "m1"
    assert chunk["delta"] == '{"q":"test"}'


def test_compress_tool_call_result_kept() -> None:
    """ToolCallResult is an atomic event and should be kept as-is."""
    buffer = [
        ToolCallResultEvent(
            tool_call_id="tc1",
            message_id="m1",
            content="result data",
            role="tool",
        ),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 1
    assert result[0]["type"] == "TOOL_CALL_RESULT"
    assert result[0]["toolCallId"] == "tc1"
    assert result[0]["content"] == "result data"


def test_compress_reasoning() -> None:
    """Reasoning Start + Message* + End -> single ReasoningMessageChunk."""
    buffer = [
        ReasoningStartEvent(message_id="r1"),
        ReasoningMessageStartEvent(message_id="r1", role="assistant"),
        ReasoningMessageContentEvent(message_id="r1", delta="Let me "),
        ReasoningMessageContentEvent(message_id="r1", delta="think..."),
        ReasoningMessageEndEvent(message_id="r1"),
        ReasoningEndEvent(message_id="r1"),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 1
    chunk = result[0]
    assert chunk["type"] == "REASONING_MESSAGE_CHUNK"
    assert chunk["messageId"] == "r1"
    assert chunk["delta"] == "Let me think..."


def test_compress_custom_event_kept() -> None:
    """CustomEvent is atomic and should be kept as-is."""
    buffer = [
        CustomEvent(name="usage_snapshot", value={"tokens": 100}),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 1
    assert result[0]["name"] == "usage_snapshot"
    assert result[0]["value"] == {"tokens": 100}


def test_compress_lifecycle_events_dropped() -> None:
    """RunStarted and RunFinished should be dropped."""
    buffer = [
        RunStartedEvent(thread_id="t1", run_id="r1"),
        RunFinishedEvent(thread_id="t1", run_id="r1"),
    ]

    result = compress_display_messages(buffer)

    assert result == []


def test_compress_full_conversation() -> None:
    """Full realistic conversation: reasoning + text + tool + result + text."""
    buffer = [
        RunStartedEvent(thread_id="t1", run_id="r1"),
        # Reasoning
        ReasoningStartEvent(message_id="r1"),
        ReasoningMessageStartEvent(message_id="r1", role="assistant"),
        ReasoningMessageContentEvent(message_id="r1", delta="thinking..."),
        ReasoningMessageEndEvent(message_id="r1"),
        ReasoningEndEvent(message_id="r1"),
        # First text (before tool)
        TextMessageStartEvent(message_id="m1", role="assistant"),
        TextMessageContentEvent(message_id="m1", delta="Let me search."),
        TextMessageEndEvent(message_id="m1"),
        # Tool call
        ToolCallStartEvent(tool_call_id="tc1", tool_call_name="web_search", parent_message_id="m1"),
        ToolCallArgsEvent(tool_call_id="tc1", delta='{"query": "test"}'),
        ToolCallEndEvent(tool_call_id="tc1"),
        # Tool result
        ToolCallResultEvent(tool_call_id="tc1", message_id="m1", content="Found results"),
        # Second text (after tool)
        TextMessageStartEvent(message_id="m2", role="assistant"),
        TextMessageContentEvent(message_id="m2", delta="Based on results: done."),
        TextMessageEndEvent(message_id="m2"),
        RunFinishedEvent(thread_id="t1", run_id="r1"),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 5
    assert result[0]["type"] == "REASONING_MESSAGE_CHUNK"
    assert result[1]["type"] == "TEXT_MESSAGE_CHUNK"
    assert result[1]["delta"] == "Let me search."
    assert result[2]["type"] == "TOOL_CALL_CHUNK"
    assert result[2]["toolCallName"] == "web_search"
    assert result[3]["type"] == "TOOL_CALL_RESULT"
    assert result[4]["type"] == "TEXT_MESSAGE_CHUNK"
    assert result[4]["delta"] == "Based on results: done."


def test_compress_empty_buffer() -> None:
    """Empty buffer produces empty result."""
    assert compress_display_messages([]) == []


def test_compress_unclosed_text_flushed() -> None:
    """Unclosed text stream (interrupted) should still be flushed."""
    buffer = [
        TextMessageStartEvent(message_id="m1", role="assistant"),
        TextMessageContentEvent(message_id="m1", delta="partial"),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 1
    assert result[0]["type"] == "TEXT_MESSAGE_CHUNK"
    assert result[0]["delta"] == "partial"


def test_compress_unclosed_tool_flushed() -> None:
    """Unclosed tool call (interrupted) should still be flushed."""
    buffer = [
        ToolCallStartEvent(tool_call_id="tc1", tool_call_name="search"),
        ToolCallArgsEvent(tool_call_id="tc1", delta='{"partial":'),
    ]

    result = compress_display_messages(buffer)

    assert len(result) == 1
    assert result[0]["type"] == "TOOL_CALL_CHUNK"
    assert result[0]["delta"] == '{"partial":'
