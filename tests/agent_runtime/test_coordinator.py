"""Unit tests for execution coordinator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import ToolApproved, ToolDenied

from netherbrain.agent_runtime.execution.coordinator import (
    _build_run_summary,
    _check_deferred,
    _collect_approvals,
    _collect_calls,
    _extract_final_message,
    _fill_uncovered,
    _get_output,
    _handle_interrupt,
    _restore_parent_state,
    build_deferred_tool_results,
)
from netherbrain.agent_runtime.models.enums import SessionStatus
from netherbrain.agent_runtime.models.input import ToolResult as NToolResult
from netherbrain.agent_runtime.models.input import UserInteraction
from netherbrain.agent_runtime.models.session import RunSummary, SessionState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_streamer(*, output: Any = "Hello!", has_run: bool = True) -> MagicMock:
    """Create a mock AgentStreamer with configurable output."""
    streamer = MagicMock()
    if has_run:
        streamer.run = MagicMock()
        result_mock = MagicMock()
        result_mock.output = output
        streamer.run.result = result_mock
        streamer.run.all_messages.return_value = []
        usage = MagicMock()
        usage.total_tokens = 100
        usage.input_tokens = 60
        usage.output_tokens = 40
        usage.requests = 2
        streamer.run.usage.return_value = usage
    else:
        streamer.run = None
    return streamer


def _mock_resumable_state(*, deferred_metadata: dict | None = None) -> MagicMock:
    """Create a mock ResumableState."""
    state = MagicMock()
    state.deferred_tool_metadata = deferred_metadata or {}
    return state


# ---------------------------------------------------------------------------
# _get_output
# ---------------------------------------------------------------------------


def test_get_output_no_run() -> None:
    streamer = _mock_streamer(has_run=False)
    assert _get_output(streamer) is None


def test_get_output_string() -> None:
    streamer = _mock_streamer(output="Hello world")
    assert _get_output(streamer) == "Hello world"


def test_get_output_deferred() -> None:
    deferred = DeferredToolRequests()
    streamer = _mock_streamer(output=deferred)
    assert _get_output(streamer) is deferred


def test_get_output_result_raises() -> None:
    streamer = MagicMock()
    streamer.run = MagicMock()
    type(streamer.run).result = property(lambda s: (_ for _ in ()).throw(RuntimeError("incomplete")))
    assert _get_output(streamer) is None


# ---------------------------------------------------------------------------
# _extract_final_message
# ---------------------------------------------------------------------------


def test_extract_final_message_string() -> None:
    streamer = _mock_streamer(output="Final answer")
    assert _extract_final_message(streamer) == "Final answer"


def test_extract_final_message_deferred() -> None:
    streamer = _mock_streamer(output=DeferredToolRequests())
    assert _extract_final_message(streamer) is None


def test_extract_final_message_no_run() -> None:
    streamer = _mock_streamer(has_run=False)
    assert _extract_final_message(streamer) is None


def test_extract_final_message_non_string() -> None:
    streamer = _mock_streamer(output=42)
    assert _extract_final_message(streamer) == "42"


def test_extract_final_message_none_output() -> None:
    streamer = _mock_streamer(output=None)
    assert _extract_final_message(streamer) is None


# ---------------------------------------------------------------------------
# _check_deferred
# ---------------------------------------------------------------------------


def test_check_deferred_true() -> None:
    streamer = _mock_streamer(output=DeferredToolRequests())
    assert _check_deferred(streamer) is True


def test_check_deferred_false() -> None:
    streamer = _mock_streamer(output="Done")
    assert _check_deferred(streamer) is False


def test_check_deferred_no_run() -> None:
    streamer = _mock_streamer(has_run=False)
    assert _check_deferred(streamer) is False


# ---------------------------------------------------------------------------
# _build_run_summary
# ---------------------------------------------------------------------------


def test_build_run_summary() -> None:
    streamer = _mock_streamer()
    summary = _build_run_summary(streamer, 1500)

    assert summary.duration_ms == 1500
    assert summary.usage.total_tokens == 100
    assert summary.usage.prompt_tokens == 60
    assert summary.usage.completion_tokens == 40
    assert summary.usage.model_requests == 2


def test_build_run_summary_no_run() -> None:
    streamer = _mock_streamer(has_run=False)
    summary = _build_run_summary(streamer, 500)

    assert summary.duration_ms == 500
    assert summary.usage.total_tokens == 0


def test_build_run_summary_usage_raises() -> None:
    streamer = _mock_streamer()
    streamer.run.usage.side_effect = RuntimeError("no usage")
    summary = _build_run_summary(streamer, 200)

    assert summary.duration_ms == 200
    assert summary.usage.total_tokens == 0


# ---------------------------------------------------------------------------
# _collect_approvals / _collect_calls
# ---------------------------------------------------------------------------


def test_collect_approvals_none() -> None:
    assert _collect_approvals(None) == {}


def test_collect_approvals_mixed() -> None:
    interactions = [
        UserInteraction(tool_call_id="a", approved=True),
        UserInteraction(tool_call_id="b", approved=False),
    ]
    result = _collect_approvals(interactions)
    assert isinstance(result["a"], ToolApproved)
    assert isinstance(result["b"], ToolDenied)


def test_collect_calls_none() -> None:
    assert _collect_calls(None) == {}


def test_collect_calls_with_output() -> None:
    results = [
        NToolResult(tool_call_id="c", output="result data"),
    ]
    calls = _collect_calls(results)
    assert isinstance(calls["c"], ToolReturn)
    assert calls["c"].return_value == "result data"


def test_collect_calls_with_error() -> None:
    results = [
        NToolResult(tool_call_id="d", error="something broke"),
    ]
    calls = _collect_calls(results)
    assert calls["d"].return_value == "something broke"


# ---------------------------------------------------------------------------
# _fill_uncovered
# ---------------------------------------------------------------------------


def test_fill_uncovered_auto_deny() -> None:
    metadata = {"x": {"type": "approval"}}
    approvals: dict = {}
    calls: dict = {}
    _fill_uncovered(metadata, approvals, calls)

    assert isinstance(approvals["x"], ToolDenied)
    assert "Auto-denied" in approvals["x"].message


def test_fill_uncovered_auto_fail() -> None:
    metadata = {"y": {"type": "call"}}
    approvals: dict = {}
    calls: dict = {}
    _fill_uncovered(metadata, approvals, calls)

    assert isinstance(calls["y"], ToolReturn)
    assert "Auto-failed" in calls["y"].return_value


def test_fill_uncovered_skips_covered() -> None:
    metadata = {"a": {"type": "approval"}, "b": {"type": "call"}}
    approvals: dict = {"a": ToolApproved()}
    calls: dict = {"b": ToolReturn(return_value="ok")}
    _fill_uncovered(metadata, approvals, calls)

    # Should not overwrite
    assert isinstance(approvals["a"], ToolApproved)
    assert calls["b"].return_value == "ok"


# ---------------------------------------------------------------------------
# build_deferred_tool_results
# ---------------------------------------------------------------------------


def test_build_deferred_no_metadata() -> None:
    state = _mock_resumable_state(deferred_metadata={})
    assert build_deferred_tool_results(state, None, None) is None


def test_build_deferred_with_approvals() -> None:
    state = _mock_resumable_state(deferred_metadata={"t1": {"type": "approval"}})
    interactions = [UserInteraction(tool_call_id="t1", approved=True)]
    result = build_deferred_tool_results(state, interactions, None)

    assert result is not None
    assert isinstance(result, DeferredToolResults)
    assert isinstance(result.approvals["t1"], ToolApproved)


def test_build_deferred_auto_fills_uncovered() -> None:
    state = _mock_resumable_state(deferred_metadata={"t1": {"type": "approval"}, "t2": {"type": "call"}})
    # Provide no feedback -> both auto-filled
    result = build_deferred_tool_results(state, [], [])

    assert result is not None
    assert isinstance(result.approvals["t1"], ToolDenied)
    assert isinstance(result.calls["t2"], ToolReturn)


# ---------------------------------------------------------------------------
# _restore_parent_state
# ---------------------------------------------------------------------------


def test_restore_parent_state_none() -> None:
    resumable, resource = _restore_parent_state(None)
    assert resumable is None
    assert resource is None


def test_restore_parent_state_empty() -> None:
    state = SessionState(context_state={}, message_history=[], environment_state={})
    resumable, resource = _restore_parent_state(state)
    assert resumable is None
    assert resource is None


def test_restore_parent_state_with_context() -> None:
    from ya_agent_sdk.context import ResumableState

    state = SessionState(
        context_state=ResumableState().model_dump(),
        message_history=[],
        environment_state={},
    )
    resumable, resource = _restore_parent_state(state)
    assert resumable is not None
    assert isinstance(resumable, ResumableState)
    assert resource is None


# ---------------------------------------------------------------------------
# _handle_interrupt
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_interrupt_with_state() -> None:
    session_manager = AsyncMock()
    db = AsyncMock()
    exported_state = SessionState(context_state={}, message_history=[], environment_state={})
    summary = RunSummary(duration_ms=500)

    result = await _handle_interrupt(
        "sess-1",
        session_manager,
        db,
        exported_state,
        "partial",
        summary,
    )

    assert result.status == SessionStatus.COMMITTED
    assert result.final_message == "partial"
    session_manager.commit_session.assert_awaited_once()


@pytest.mark.anyio
async def test_handle_interrupt_no_state() -> None:
    session_manager = AsyncMock()
    db = AsyncMock()
    summary = RunSummary(duration_ms=200)

    result = await _handle_interrupt(
        "sess-2",
        session_manager,
        db,
        None,
        None,
        summary,
    )

    assert result.status == SessionStatus.FAILED
    session_manager.fail_session.assert_awaited_once()


@pytest.mark.anyio
async def test_handle_interrupt_commit_fails() -> None:
    session_manager = AsyncMock()
    session_manager.commit_session.side_effect = RuntimeError("db error")
    db = AsyncMock()
    exported_state = SessionState(context_state={}, message_history=[], environment_state={})
    summary = RunSummary(duration_ms=300)

    result = await _handle_interrupt(
        "sess-3",
        session_manager,
        db,
        exported_state,
        None,
        summary,
    )

    assert result.status == SessionStatus.FAILED
    session_manager.fail_session.assert_awaited_once()


# ---------------------------------------------------------------------------
# execute_session (integration with mocks)
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> Any:
    """Build a minimal ResolvedConfig."""
    from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
    from netherbrain.agent_runtime.models.enums import ShellMode
    from netherbrain.agent_runtime.models.preset import ModelPreset, SubagentSpec, ToolsetSpec

    defaults = {
        "preset_id": "test-preset",
        "model": ModelPreset(name="openai:gpt-4o"),
        "system_prompt": "You are a helpful assistant.",
        "toolsets": [ToolsetSpec(toolset_name="shell")],
        "subagents": SubagentSpec(),
        "shell_mode": ShellMode.LOCAL,
        "project_ids": ["test-project"],
        "container_id": None,
        "container_workdir": None,
    }
    defaults.update(overrides)
    return ResolvedConfig(**defaults)


@pytest.mark.anyio
@patch("netherbrain.agent_runtime.execution.coordinator.create_service_runtime")
@patch("netherbrain.agent_runtime.execution.coordinator.map_input_to_prompt")
async def test_execute_session_success(
    mock_map_input: AsyncMock,
    mock_create_runtime: MagicMock,
    tmp_path: Any,
) -> None:
    """Test successful execution flow."""
    from netherbrain.agent_runtime.execution.coordinator import execute_session
    from netherbrain.agent_runtime.models.input import text_part

    # Setup mocks
    mock_map_input.return_value = "Hello"

    mock_runtime = MagicMock()
    mock_runtime.ctx.export_state.return_value = MagicMock(model_dump=lambda: {})
    mock_runtime.env.export_resource_state = AsyncMock(return_value=None)

    mock_paths = MagicMock()
    mock_create_runtime.return_value = (mock_runtime, mock_paths)

    mock_streamer = _mock_streamer(output="Done!")

    # Make stream_agent an async context manager that yields mock_streamer
    async def _fake_stream_agent(runtime, **kwargs):
        class _CM:
            async def __aenter__(self):
                return mock_streamer

            async def __aexit__(self, *args):
                pass

        return _CM()

    mock_session_manager = AsyncMock()
    mock_registry = MagicMock()
    mock_settings = MagicMock()
    mock_settings.data_root = str(tmp_path)
    mock_settings.data_prefix = None
    mock_db = AsyncMock()

    with patch(
        "ya_agent_sdk.agents.main.stream_agent",
    ) as mock_stream:
        # Create a proper async context manager
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_streamer)
        cm.__aexit__ = AsyncMock(return_value=False)
        # Make iterating the streamer return no events (async iterator)
        mock_streamer.__aiter__ = MagicMock(return_value=mock_streamer)
        mock_streamer.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
        mock_stream.return_value = cm

        result = await execute_session(
            _make_config(),
            [text_part("Hello")],
            session_id="sess-1",
            conversation_id="conv-1",
            session_manager=mock_session_manager,
            registry=mock_registry,
            settings=mock_settings,
            db=mock_db,
        )

    assert result.status == SessionStatus.COMMITTED
    assert result.final_message == "Done!"
    assert result.session_id == "sess-1"
    mock_session_manager.commit_session.assert_awaited_once()
    mock_registry.register.assert_called_once()


@pytest.mark.anyio
@patch("netherbrain.agent_runtime.execution.coordinator.create_service_runtime")
@patch("netherbrain.agent_runtime.execution.coordinator.map_input_to_prompt")
async def test_execute_session_failure(
    mock_map_input: AsyncMock,
    mock_create_runtime: MagicMock,
    tmp_path: Any,
) -> None:
    """Test failure during execution."""
    from netherbrain.agent_runtime.execution.coordinator import execute_session
    from netherbrain.agent_runtime.models.input import text_part

    mock_map_input.return_value = "Hello"
    mock_runtime = MagicMock()
    mock_paths = MagicMock()
    mock_create_runtime.return_value = (mock_runtime, mock_paths)

    mock_session_manager = AsyncMock()
    mock_registry = MagicMock()
    mock_settings = MagicMock()
    mock_settings.data_root = str(tmp_path)
    mock_db = AsyncMock()

    with patch(
        "ya_agent_sdk.agents.main.stream_agent",
    ) as mock_stream:
        mock_stream.side_effect = RuntimeError("LLM unavailable")

        result = await execute_session(
            _make_config(),
            [text_part("Hello")],
            session_id="sess-2",
            conversation_id="conv-1",
            session_manager=mock_session_manager,
            registry=mock_registry,
            settings=mock_settings,
            db=mock_db,
        )

    assert result.status == SessionStatus.FAILED
    mock_session_manager.fail_session.assert_awaited_once()
