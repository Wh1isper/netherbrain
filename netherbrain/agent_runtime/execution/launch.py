"""Shared execution launch logic for API routers.

Encapsulates the common workflow of creating a session, setting up
transport, and launching the execution coordinator as a background task.

Both conversation-level and session-level routers delegate here after
resolving their specific parameters (config, parent state, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from netherbrain.agent_runtime.context import RuntimeSession
from netherbrain.agent_runtime.execution.coordinator import execute_session
from netherbrain.agent_runtime.models.enums import SessionType, Transport
from netherbrain.agent_runtime.transport.base import EventTransport
from netherbrain.agent_runtime.transport.redis_stream import RedisStreamTransport
from netherbrain.agent_runtime.transport.sse import SSETransport

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
    from netherbrain.agent_runtime.managers.execution import ExecutionManager
    from netherbrain.agent_runtime.managers.sessions import SessionManager
    from netherbrain.agent_runtime.models.api import ExternalToolSpec
    from netherbrain.agent_runtime.models.input import InputPart, ToolResult, UserInteraction
    from netherbrain.agent_runtime.models.session import SessionState
    from netherbrain.agent_runtime.registry import SessionRegistry
    from netherbrain.agent_runtime.settings import NetherSettings

logger = logging.getLogger(__name__)

# Background tasks must be stored to prevent garbage collection.
_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class LaunchResult:
    """Outcome of launching an execution -- enough info to build the response."""

    session_id: str
    conversation_id: str
    transport: Transport
    stream_key: str | None = None
    sse_transport: SSETransport | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def launch_session(
    *,
    db: AsyncSession,
    session_factory: async_sessionmaker,
    session_manager: SessionManager,
    registry: SessionRegistry,
    settings: NetherSettings,
    redis: aioredis.Redis | None,
    config: ResolvedConfig,
    input_parts: Sequence[InputPart],
    transport: Transport = Transport.SSE,
    # Parent / conversation
    parent_session_id: str | None = None,
    parent_state: SessionState | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
    # Feedback (for deferred tools)
    user_interactions: Sequence[UserInteraction] | None = None,
    tool_results: Sequence[ToolResult] | None = None,
    # Session classification
    session_type: SessionType = SessionType.AGENT,
    spawned_by: str | None = None,
    subagent_name: str | None = None,
    external_tools: Sequence[ExternalToolSpec] | None = None,
    execution_manager: ExecutionManager | None = None,
) -> LaunchResult:
    """Create a session, set up transport, and launch execution in background.

    This is the shared entry point for ``/conversations/run``,
    ``/conversations/fork``, and ``/sessions/execute``.

    Parameters
    ----------
    db:
        Request-scoped DB session (used for creating the session row).
    session_factory:
        DB session factory for the background task (outlives request).
    session_manager:
        Session lifecycle manager.
    registry:
        In-memory session registry.
    settings:
        Service settings.
    redis:
        Redis client (required for stream transport).
    config:
        Fully resolved execution config.
    input_parts:
        User input parts.
    transport:
        Event delivery mode (SSE or Redis stream).
    parent_session_id:
        Parent session for continuation / fork.
    parent_state:
        Parent session state for resuming.
    conversation_id:
        Conversation ID (None = new conversation, create_session assigns it).
    user_interactions:
        HITL approval decisions.
    tool_results:
        External tool results.
    session_type:
        Agent or async_subagent.
    spawned_by:
        For async subagents: the spawner session ID.
    subagent_name:
        For async subagents: the name from the parent's SubagentRef.

    Returns
    -------
    LaunchResult
        Session and transport info for building the HTTP response.

    Raises
    ------
    ValueError
        If stream transport is requested but Redis is not configured.
    """
    # -- Validate transport requirements ---------------------------------------
    if transport == Transport.STREAM and redis is None:
        msg = "Stream transport requires Redis (NETHER_REDIS_URL is unset)"
        raise ValueError(msg)

    # -- Create session row (PG) -----------------------------------------------
    session_row = await session_manager.create_session(
        db,
        parent_session_id=parent_session_id,
        conversation_id=conversation_id,
        user_id=user_id,
        preset_id=config.preset_id,
        project_ids=config.project_ids,
        session_type=session_type,
        transport=transport,
        spawned_by=spawned_by,
        input_parts=[p.model_dump() for p in input_parts] if input_parts else None,
    )
    session_id = session_row.session_id
    resolved_conversation_id = session_row.conversation_id

    # -- Set up event transport ------------------------------------------------
    sse_transport: SSETransport | None = None
    stream_key: str | None = None

    if transport == Transport.SSE:
        sse_transport = SSETransport(session_id)
        event_transport = sse_transport
    else:
        assert redis is not None  # noqa: S101
        redis_transport = RedisStreamTransport(redis, session_id)
        event_transport = redis_transport
        stream_key = redis_transport.key

    # -- Pre-register session in registry ------------------------------------
    # The session must be visible in the registry immediately so that
    # GET /events (bridge endpoint) can find it before the background
    # task reaches the coordinator's full initialisation.
    runtime_session = RuntimeSession(
        session_id=session_id,
        conversation_id=resolved_conversation_id,
        parent_session_id=parent_session_id,
        preset_id=config.preset_id,
        project_ids=config.project_ids,
        session_type=SessionType.ASYNC_SUBAGENT if subagent_name else SessionType.AGENT,
        transport=transport,
        subagent_name=subagent_name,
        stream_key=stream_key,
    )
    registry.register(runtime_session)

    # -- Launch background task ------------------------------------------------
    task = asyncio.create_task(
        _run_execution(
            session_factory=session_factory,
            session_manager=session_manager,
            registry=registry,
            settings=settings,
            redis=redis,
            config=config,
            input_parts=list(input_parts),
            session_id=session_id,
            conversation_id=resolved_conversation_id,
            parent_session_id=parent_session_id,
            parent_state=parent_state,
            transport=transport,
            user_interactions=list(user_interactions) if user_interactions else None,
            tool_results=list(tool_results) if tool_results else None,
            event_transport=event_transport,
            subagent_name=subagent_name,
            external_tools=list(external_tools) if external_tools else None,
            runtime_session=runtime_session,
            execution_manager=execution_manager,
            user_id=user_id,
        ),
        name=f"execute-{session_id}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return LaunchResult(
        session_id=session_id,
        conversation_id=resolved_conversation_id,
        transport=transport,
        stream_key=stream_key,
        sse_transport=sse_transport,
    )


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _run_execution(
    *,
    session_factory: async_sessionmaker,
    session_manager: SessionManager,
    registry: SessionRegistry,
    settings: NetherSettings,
    redis: aioredis.Redis | None,
    config: ResolvedConfig,
    input_parts: list[InputPart],
    session_id: str,
    conversation_id: str,
    parent_session_id: str | None,
    parent_state: SessionState | None,
    transport: Transport,
    user_interactions: list[UserInteraction] | None,
    tool_results: list[ToolResult] | None,
    event_transport: object,
    subagent_name: str | None = None,
    external_tools: list[ExternalToolSpec] | None = None,
    runtime_session: RuntimeSession | None = None,
    execution_manager: ExecutionManager | None = None,
    user_id: str | None = None,
) -> None:
    """Background task wrapper for execute_session.

    Creates its own DB session (the request session is already closed)
    and ensures proper cleanup on any failure.
    """
    async with session_factory() as bg_db:
        try:
            result = await execute_session(
                config,
                input_parts,
                session_id=session_id,
                conversation_id=conversation_id,
                session_manager=session_manager,
                registry=registry,
                settings=settings,
                db=bg_db,
                parent_session_id=parent_session_id,
                parent_state=parent_state,
                transport=transport,
                user_interactions=user_interactions,
                tool_results=tool_results,
                event_transport=event_transport if isinstance(event_transport, EventTransport) else None,
                subagent_name=subagent_name,
                session_factory=session_factory,
                redis=redis,
                external_tools=external_tools,
                runtime_session=runtime_session,
                execution_manager=execution_manager,
                user_id=user_id,
            )
            logger.info(
                "Execution completed: session=%s status=%s",
                session_id,
                result.status,
            )
        except Exception:
            logger.exception("Background execution failed: session=%s", session_id)
            # Ensure session is marked failed if coordinator didn't handle it.
            try:
                await session_manager.fail_session(bg_db, session_id)
            except Exception:
                logger.exception("Failed to mark session %s as failed", session_id)
