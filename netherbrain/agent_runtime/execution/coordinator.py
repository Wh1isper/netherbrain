"""Execution coordinator -- orchestrates setup, run, and finalize.

The coordinator manages the full lifecycle of a single agent session:

1. **Setup**: Create SDK runtime, map input, register session
2. **Execute**: Run the agent via ``stream_agent``, dispatch events
3. **Finalize**: Export state, commit session, clean up

The caller (API layer) is responsible for:

- Creating the session row (``session_manager.create_session``)
- Resolving config (``resolve_config``)
- Setting up transport (SSE / Redis stream)
- Decoupling event delivery from execution

Pipeline execution and transport delivery are decoupled. The agent runs
to completion regardless of consumer speed or disconnection.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ag_ui.core import BaseEvent
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolReturn
from pydantic_ai.tools import ToolApproved, ToolDenied

from netherbrain.agent_runtime.context import RuntimeSession
from netherbrain.agent_runtime.execution.events import (
    MAIN_AGENT_ID,
    ModelUsage,
    PipelineCompleted,
    PipelineStarted,
    PipelineUsage,
)
from netherbrain.agent_runtime.execution.hooks import UsageSnapshotEmitter
from netherbrain.agent_runtime.execution.input import map_input_to_prompt
from netherbrain.agent_runtime.execution.runtime import create_service_runtime
from netherbrain.agent_runtime.models.enums import SessionStatus, Transport
from netherbrain.agent_runtime.models.input import InputPart, ToolResult, UserInteraction
from netherbrain.agent_runtime.models.session import ModelUsageSummary, RunSummary, SessionState, UsageSummary
from netherbrain.agent_runtime.streaming.compress import compress_display_messages
from netherbrain.agent_runtime.streaming.protocols.agui import AGUIProtocol
from netherbrain.agent_runtime.streaming.protocols.base import ProtocolAdapter
from netherbrain.agent_runtime.transport.base import EventTransport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from ya_agent_sdk.agents.main import AgentRuntime, AgentStreamer
    from ya_agent_sdk.context import ResumableState, StreamEvent

    from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
    from netherbrain.agent_runtime.managers.sessions import SessionManager
    from netherbrain.agent_runtime.registry import SessionRegistry
    from netherbrain.agent_runtime.settings import NetherSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Outcome of a completed agent session."""

    session_id: str
    status: SessionStatus
    final_message: str | None = None
    run_summary: RunSummary | None = None
    deferred_requests: DeferredToolRequests | None = None


# ---------------------------------------------------------------------------
# Deferred tool mapping
# ---------------------------------------------------------------------------


def build_deferred_tool_results(
    parent_state: ResumableState,
    user_interactions: Sequence[UserInteraction] | None,
    tool_results: Sequence[ToolResult] | None,
) -> DeferredToolResults | None:
    """Build ``DeferredToolResults`` from user feedback.

    Maps ``UserInteraction`` (HITL approvals) and ``ToolResult`` (external
    results) to the SDK's ``DeferredToolResults`` format.

    Pending deferred tools not covered by feedback are auto-denied/auto-failed.
    """
    metadata = parent_state.deferred_tool_metadata
    if not metadata:
        return None

    approvals = _collect_approvals(user_interactions)
    calls = _collect_calls(tool_results)
    _fill_uncovered(metadata, approvals, calls)

    if not approvals and not calls:
        return None

    return DeferredToolResults(
        approvals=approvals,
        calls=calls,
        metadata=metadata,
    )


def _collect_approvals(
    interactions: Sequence[UserInteraction] | None,
) -> dict[str, bool | ToolApproved | ToolDenied]:
    approvals: dict[str, bool | ToolApproved | ToolDenied] = {}
    if interactions:
        for interaction in interactions:
            if interaction.approved:
                approvals[interaction.tool_call_id] = ToolApproved()
            else:
                approvals[interaction.tool_call_id] = ToolDenied()
    return approvals


def _collect_calls(
    results: Sequence[ToolResult] | None,
) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    if results:
        for result in results:
            calls[result.tool_call_id] = ToolReturn(
                return_value=result.error or result.output or "",
            )
    return calls


def _fill_uncovered(
    metadata: dict[str, dict[str, Any]],
    approvals: dict[str, bool | ToolApproved | ToolDenied],
    calls: dict[str, Any],
) -> None:
    """Auto-deny/fail deferred tools not covered by user feedback."""
    for tool_call_id, meta in metadata.items():
        tool_type = meta.get("type", "approval")
        if tool_type == "approval" and tool_call_id not in approvals:
            approvals[tool_call_id] = ToolDenied(message="Auto-denied: no response provided")
        elif tool_type == "call" and tool_call_id not in calls:
            calls[tool_call_id] = ToolReturn(
                return_value="Auto-failed: no result provided",
            )


# ---------------------------------------------------------------------------
# Parent state restoration
# ---------------------------------------------------------------------------


def _restore_parent_state(
    parent_state: SessionState | None,
) -> tuple[ResumableState | None, Any]:
    """Extract resumable state and resource state from a parent session."""
    if parent_state is None:
        return None, None

    from ya_agent_sdk.context import ResumableState as _RS

    resumable_state: ResumableState | None = None
    resource_state = None

    if parent_state.context_state:
        resumable_state = _RS.model_validate(parent_state.context_state)

    if parent_state.environment_state:
        from y_agent_environment.resources import ResourceRegistryState

        resource_state = ResourceRegistryState.model_validate(parent_state.environment_state)

    return resumable_state, resource_state


# ---------------------------------------------------------------------------
# State export helpers
# ---------------------------------------------------------------------------


def _get_output(streamer: AgentStreamer) -> object | None:
    """Safely get the output from the agent run result."""
    if streamer.run is None:
        return None
    try:
        result = streamer.run.result  # may raise if incomplete
    except Exception:
        return None
    else:
        return result.output if result is not None else None


def _extract_final_message(streamer: AgentStreamer) -> str | None:
    """Extract the final text output from the agent run."""
    output = _get_output(streamer)
    if output is None or isinstance(output, DeferredToolRequests):
        return None
    if isinstance(output, str):
        return output
    return str(output)


def _check_deferred(streamer: AgentStreamer) -> bool:
    """Check if the run produced deferred tool requests."""
    return isinstance(_get_output(streamer), DeferredToolRequests)


def _serialize_deferred_tools(deferred: DeferredToolRequests) -> dict:
    """Serialize ``DeferredToolRequests`` to a JSON-friendly dict.

    Produces a lightweight representation for the session row so
    clients can render approval UI without loading context_state.
    """

    def _serialize_call(part: Any) -> dict:
        return {
            "tool_call_id": part.tool_call_id,
            "tool_name": part.tool_name,
            "args": part.args_as_json_str() if part.args else "",
        }

    return {
        "calls": [_serialize_call(c) for c in deferred.calls],
        "approvals": [_serialize_call(a) for a in deferred.approvals],
    }


async def _export_session_state(
    runtime: AgentRuntime,
    streamer: AgentStreamer,
) -> SessionState:
    """Export full session state from the SDK runtime.

    Must be called while the runtime is still alive (inside the
    ``stream_agent`` context manager).
    """
    # Context state (ResumableState -> dict)
    context_state = runtime.ctx.export_state()

    # Message history (ModelMessage list -> JSON-serializable dicts)
    messages = streamer.run.all_messages() if streamer.run else []
    serialized_messages = ModelMessagesTypeAdapter.dump_python(messages, mode="json") if messages else []

    # Environment state (ResourceRegistryState -> dict)
    try:
        env_state = await runtime.env.export_resource_state()
        env_dict = env_state.model_dump() if env_state else {}
    except Exception:
        logger.debug("Could not export environment state", exc_info=True)
        env_dict = {}

    return SessionState(
        context_state=context_state.model_dump(),
        message_history=serialized_messages,
        environment_state=env_dict,
    )


def _build_pipeline_usage(
    runtime: AgentRuntime,
    streamer: AgentStreamer,
    model_id: str,
) -> PipelineUsage:
    """Build aggregated usage from main run + extra usages (subagents, compact, etc.)."""
    usage = PipelineUsage()

    if streamer.run:
        try:
            sdk_usage = streamer.run.usage()
            usage.add(model_id, ModelUsage.from_run_usage(sdk_usage))
        except Exception:
            logger.debug("Could not extract main usage", exc_info=True)

    # Extra usages from subagents, image understanding, compact, etc.
    try:
        for record in runtime.ctx.extra_usages:
            usage.add(record.model_id, ModelUsage.from_run_usage(record.usage))
    except Exception:
        logger.debug("Could not extract extra usages", exc_info=True)

    return usage


def _pipeline_usage_to_summary(usage: PipelineUsage) -> UsageSummary:
    """Convert dataclass ``PipelineUsage`` to Pydantic ``UsageSummary`` for PG storage."""
    from dataclasses import asdict

    return UsageSummary(
        model_usages={
            model_id: ModelUsageSummary(**asdict(model_usage)) for model_id, model_usage in usage.model_usages.items()
        }
    )


def _build_run_summary(
    runtime: AgentRuntime,
    streamer: AgentStreamer,
    model_id: str,
    duration_ms: int,
) -> tuple[RunSummary, PipelineUsage]:
    """Build run summary and pipeline usage from SDK data.

    Returns both the Pydantic ``RunSummary`` (for PG storage) and the
    dataclass ``PipelineUsage`` (for the ``PipelineCompleted`` event).
    """
    pipeline_usage = _build_pipeline_usage(runtime, streamer, model_id)
    summary = RunSummary(
        duration_ms=duration_ms,
        usage=_pipeline_usage_to_summary(pipeline_usage),
    )
    return summary, pipeline_usage


# ---------------------------------------------------------------------------
# Interrupt handling
# ---------------------------------------------------------------------------


async def _handle_interrupt(
    session_id: str,
    session_manager: SessionManager,
    db: AsyncSession,
    exported_state: SessionState | None,
    exported_final: str | None,
    summary: RunSummary,
    adapter: ProtocolAdapter | None = None,
) -> ExecutionResult:
    """Handle AgentInterrupted: partial commit or fail."""
    if exported_state is not None:
        try:
            await session_manager.commit_session(
                db,
                session_id,
                state=exported_state,
                final_message=exported_final,
                run_summary=summary,
                display_messages=_compress_adapter_buffer(adapter),
                status=SessionStatus.COMMITTED,
            )
        except Exception:
            logger.exception("Failed to commit interrupted session %s", session_id)
            await session_manager.fail_session(db, session_id)
            return ExecutionResult(
                session_id=session_id,
                status=SessionStatus.FAILED,
                run_summary=summary,
            )
    else:
        await session_manager.fail_session(db, session_id)

    status = SessionStatus.COMMITTED if exported_state else SessionStatus.FAILED
    logger.info(
        "Session %s interrupted: status=%s, duration=%dms",
        session_id,
        status,
        summary.duration_ms,
    )
    return ExecutionResult(
        session_id=session_id,
        status=status,
        final_message=exported_final,
        run_summary=summary,
    )


# ---------------------------------------------------------------------------
# Display messages compression helper
# ---------------------------------------------------------------------------


def _compress_adapter_buffer(adapter: ProtocolAdapter | None) -> list[dict] | None:
    """Compress the adapter's event buffer into display message chunks.

    Returns None if the adapter is not an AGUIProtocol or has no buffer.
    """
    if adapter is None:
        return None
    if not isinstance(adapter, AGUIProtocol):
        return None
    if not adapter.buffer:
        return None
    return compress_display_messages(adapter.buffer)


# ---------------------------------------------------------------------------
# Event delivery helpers
# ---------------------------------------------------------------------------


def _wrap_pipeline_event(event: Any) -> StreamEvent:
    """Wrap a pipeline event (AgentEvent subclass) in a StreamEvent."""
    from ya_agent_sdk.context import StreamEvent as _SE

    return _SE(
        agent_id=MAIN_AGENT_ID,
        agent_name=MAIN_AGENT_ID,
        event=event,
    )


async def _deliver(
    events: AsyncIterator[BaseEvent],
    transport: EventTransport,
) -> None:
    """Deliver protocol events to transport, swallowing transport errors.

    Execution must run to completion regardless of transport failures
    (spec: guaranteed delivery to state store, best-effort to transport).
    """
    async for event in events:
        try:
            await transport.send(event)
        except Exception:
            logger.warning(
                "Transport send failed for event %s, continuing",
                event.type,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------


async def execute_session(  # noqa: C901
    config: ResolvedConfig,
    input_parts: Sequence[InputPart],
    *,
    session_id: str,
    conversation_id: str,
    session_manager: SessionManager,
    registry: SessionRegistry,
    settings: NetherSettings,
    db: AsyncSession,
    parent_session_id: str | None = None,
    parent_state: SessionState | None = None,
    transport: Transport = Transport.SSE,
    user_interactions: Sequence[UserInteraction] | None = None,
    tool_results: Sequence[ToolResult] | None = None,
    event_transport: EventTransport | None = None,
    protocol_adapter: ProtocolAdapter | None = None,
) -> ExecutionResult:
    """Execute an agent session to completion.

    This is the main entry point for the execution pipeline. It handles
    the full lifecycle: setup, run, and finalize.

    Parameters
    ----------
    config:
        Fully resolved execution config (from ``resolve_config``).
    input_parts:
        User input parts to map to SDK UserPrompt.
    session_id:
        Pre-created session ID (from ``session_manager.create_session``).
    conversation_id:
        Conversation this session belongs to.
    session_manager:
        For committing / failing the session after execution.
    registry:
        For registering the live session (interrupt / steering).
    settings:
        Service settings (data_root, etc.).
    db:
        Database session for commit operations.
    parent_session_id:
        Parent session for continuation / fork.
    parent_state:
        Parent session state (for resuming context and history).
    transport:
        Event delivery transport type.
    user_interactions:
        HITL approval decisions (when continuing from ``awaiting_tool_results``).
    tool_results:
        External tool results (when continuing from ``awaiting_tool_results``).
    event_transport:
        Transport backend for delivering protocol events (SSE or Redis
        Stream).  If ``None``, protocol events are not delivered (useful
        for testing or fire-and-forget execution).
    protocol_adapter:
        Protocol adapter for converting SDK events to protocol events.
        Defaults to ``AGUIProtocol`` if not provided.

    Returns
    -------
    ExecutionResult
        Outcome of the execution (status, final_message, summary).
    """
    from ya_agent_sdk.agents.main import AgentInterrupted, stream_agent

    start_time = time.monotonic()

    # -- Protocol adapter (default: AG-UI) -------------------------------------
    adapter = protocol_adapter or AGUIProtocol()

    # -- Usage tracking hook ---------------------------------------------------
    model_id = config.model.name
    usage_emitter = UsageSnapshotEmitter(session_id=session_id, model_id=model_id)

    # -- Restore parent state --------------------------------------------------
    resumable_state, resource_state = _restore_parent_state(parent_state)

    # -- Create runtime --------------------------------------------------------
    runtime, paths = create_service_runtime(
        config,
        settings,
        state=resumable_state,
        resource_state=resource_state,
    )

    # -- Map input -------------------------------------------------------------
    user_prompt = await map_input_to_prompt(input_parts, paths)

    # -- Build deferred tool results (if continuing) ---------------------------
    deferred_results = None
    if resumable_state and (user_interactions or tool_results):
        deferred_results = build_deferred_tool_results(
            resumable_state,
            user_interactions,
            tool_results,
        )

    # -- Register session in memory --------------------------------------------
    stream_key = f"nether:stream:{session_id}" if transport == Transport.STREAM else None
    runtime_session = RuntimeSession(
        session_id=session_id,
        conversation_id=conversation_id,
        parent_session_id=parent_session_id,
        preset_id=config.preset_id,
        project_ids=config.project_ids,
        transport=transport,
        sdk_context=runtime.ctx,
        stream_key=stream_key,
    )
    registry.register(runtime_session)

    # -- Execute and finalize --------------------------------------------------
    # Variables to carry across the async-with boundary.  State export happens
    # INSIDE stream_agent's context manager (runtime is still alive there).
    # AgentInterrupted is raised by stream_agent.__aexit__, so code between
    # the for-loop and the context-exit still runs.
    exported_state: SessionState | None = None
    exported_final: str | None = None
    exported_summary: RunSummary | None = None
    exported_pipeline_usage: PipelineUsage | None = None
    is_deferred = False

    try:
        # -- Emit PipelineStarted (flows through adapter.on_event) -------------
        if event_transport:
            started = _wrap_pipeline_event(
                PipelineStarted(
                    event_id=session_id,
                    session_id=session_id,
                    conversation_id=conversation_id,
                )
            )
            await _deliver(adapter.on_event(started), event_transport)

        async with stream_agent(
            runtime,
            user_prompt=user_prompt or None,
            deferred_tool_results=deferred_results,
            post_node_hook=usage_emitter.post_node_hook,
        ) as streamer:
            runtime_session.streamer = streamer

            # -- Stream SDK events through protocol adapter --------------------
            # UsageSnapshot events arrive here via output_queue injection.
            async for event in streamer:
                if event_transport:
                    await _deliver(adapter.on_event(event), event_transport)

            # Still inside stream_agent context -- runtime is alive.
            duration_ms = int((time.monotonic() - start_time) * 1000)
            exported_final = _extract_final_message(streamer)
            exported_summary, exported_pipeline_usage = _build_run_summary(
                runtime,
                streamer,
                model_id,
                duration_ms,
            )
            exported_state = await _export_session_state(runtime, streamer)
            is_deferred = _check_deferred(streamer)

        # Normal completion (no exception from __aexit__).
        status = SessionStatus.AWAITING_TOOL_RESULTS if is_deferred else SessionStatus.COMMITTED

        assert exported_state is not None  # noqa: S101

        # Serialize deferred tools for display (if HITL pending).
        deferred_tools_data: dict | None = None
        deferred_req: DeferredToolRequests | None = None
        if is_deferred:
            output = _get_output(streamer)
            if isinstance(output, DeferredToolRequests):
                deferred_req = output
                deferred_tools_data = _serialize_deferred_tools(output)

        await session_manager.commit_session(
            db,
            session_id,
            state=exported_state,
            final_message=exported_final,
            deferred_tools=deferred_tools_data,
            run_summary=exported_summary,
            display_messages=_compress_adapter_buffer(adapter),
            status=status,
        )

        # -- Emit PipelineCompleted (flows through adapter.on_event) -----------
        if event_transport:
            completed = _wrap_pipeline_event(
                PipelineCompleted(
                    event_id=session_id,
                    session_id=session_id,
                    reply=exported_final,
                    usage=exported_pipeline_usage or PipelineUsage(),
                )
            )
            await _deliver(adapter.on_event(completed), event_transport)
            await event_transport.close()

        logger.info(
            "Session %s completed: status=%s, duration=%dms",
            session_id,
            status,
            exported_summary.duration_ms if exported_summary else 0,
        )

        return ExecutionResult(
            session_id=session_id,
            status=status,
            final_message=exported_final,
            run_summary=exported_summary,
            deferred_requests=deferred_req,
        )

    except AgentInterrupted:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        summary = exported_summary or RunSummary(duration_ms=duration_ms)

        # -- Emit run_error (interrupted) --------------------------------------
        if event_transport:
            await _deliver(
                adapter.on_error(code="interrupted", message="Session interrupted"),
                event_transport,
            )
            await event_transport.close()

        return await _handle_interrupt(
            session_id,
            session_manager,
            db,
            exported_state,
            exported_final,
            summary,
            adapter=adapter,
        )

    except Exception:
        logger.exception("Session %s failed", session_id)
        duration_ms = int((time.monotonic() - start_time) * 1000)
        await session_manager.fail_session(db, session_id)

        # -- Emit run_error (failure) ------------------------------------------
        if event_transport:
            await _deliver(
                adapter.on_error(code="execution_error", message="Session execution failed"),
                event_transport,
            )
            await event_transport.close()

        return ExecutionResult(
            session_id=session_id,
            status=SessionStatus.FAILED,
            run_summary=RunSummary(duration_ms=duration_ms),
        )
