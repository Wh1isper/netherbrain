"""Execution manager -- orchestrates config resolution, session launch, and control.

Coordinates between the config resolver, session manager, registry, and the
execution launch pipeline. Process-level singleton initialised in app lifespan.

All methods raise domain exceptions (never HTTP exceptions). The router layer
translates these to appropriate HTTP responses.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ya_agent_sdk.context import BusMessage

from netherbrain.agent_runtime.context import RuntimeSession
from netherbrain.agent_runtime.execution.launch import LaunchResult, launch_session
from netherbrain.agent_runtime.execution.resolver import (
    ConfigOverride,
    resolve_config,
)
from netherbrain.agent_runtime.managers.conversations import (
    ConversationNotFoundError,
    get_conversation,
    update_conversation,
)
from netherbrain.agent_runtime.models.api import ConversationUpdate
from netherbrain.agent_runtime.models.enums import SessionStatus, Transport
from netherbrain.agent_runtime.models.input import InputPart, ToolResult, UserInteraction

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from netherbrain.agent_runtime.db.tables import Session as SessionRow
    from netherbrain.agent_runtime.managers.sessions import SessionManager
    from netherbrain.agent_runtime.models.session import SessionState
    from netherbrain.agent_runtime.registry import SessionRegistry
    from netherbrain.agent_runtime.settings import NetherSettings


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class ConversationBusyError(Exception):
    """Conversation already has an active agent session."""

    def __init__(self, active: RuntimeSession) -> None:
        self.active_session = active
        super().__init__(f"Conversation '{active.conversation_id}' already has an active session")


class NoActiveSessionError(LookupError):
    """No active agent session found."""

    def __init__(self, identifier: str) -> None:
        super().__init__(f"No active session: {identifier}")


class SessionContextNotReadyError(Exception):
    """Session SDK context not yet available for steering."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session '{session_id}' context not yet available")


class InputRequiredError(ValueError):
    """At least one input type is required."""

    def __init__(self) -> None:
        super().__init__("At least one of input, user_interactions, or tool_results is required")


class SteeringTextRequiredError(ValueError):
    """Steering input must contain text."""

    def __init__(self) -> None:
        super().__init__("Steering input must contain text")


class StreamTransportMismatchError(Exception):
    """Active session uses a different transport than expected."""

    def __init__(self, expected: Transport, actual: Transport) -> None:
        super().__init__(f"Expected transport '{expected}', but active session uses '{actual}'")


class SessionNotInConversationError(ValueError):
    """Referenced session does not belong to the conversation."""

    def __init__(self, session_id: str, conversation_id: str) -> None:
        super().__init__(f"Session '{session_id}' does not belong to conversation '{conversation_id}'")


class NoCommittedSessionError(LookupError):
    """No committed sessions available to fork from."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"No committed sessions in conversation '{conversation_id}'")


# ---------------------------------------------------------------------------
# ExecutionManager
# ---------------------------------------------------------------------------


class ExecutionManager:
    """Orchestrates execution lifecycle for conversations and sessions.

    Coordinates between config resolution, session management, the
    in-memory registry, and the background execution pipeline.

    Process-level singleton initialised in app lifespan.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        registry: SessionRegistry,
        settings: NetherSettings,
        session_factory: async_sessionmaker,
        redis: aioredis.Redis | None,
    ) -> None:
        self._session_manager = session_manager
        self._registry = registry
        self._settings = settings
        self._session_factory = session_factory
        self._redis = redis

    # -- Conversation operations -----------------------------------------------

    async def run_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: str | None = None,
        preset_id: str | None = None,
        input_parts: Sequence[InputPart] | None = None,
        user_interactions: Sequence[UserInteraction] | None = None,
        tool_results: Sequence[ToolResult] | None = None,
        workspace_id: str | None = None,
        project_ids: list[str] | None = None,
        config_override: dict | None = None,
        metadata: dict | None = None,
        transport: Transport = Transport.SSE,
    ) -> LaunchResult:
        """Create a new conversation or continue an existing one.

        Raises
        ------
        InputRequiredError: No input provided.
        ConversationNotFoundError: Conversation ID not found.
        ConversationBusyError: Conversation already has an active session.
        NoPresetError: Preset not found and no default configured.
        WorkspaceNotFoundError: Referenced workspace not found.
        ProjectConflictError: workspace_id and project_ids both specified.
        ValueError: Stream transport requested without Redis.
        """
        if not input_parts and not user_interactions and not tool_results:
            raise InputRequiredError

        parent_session_id: str | None = None
        parent_state: SessionState | None = None
        parent_project_ids: list[str] | None = None

        if conversation_id is not None:
            # Continue existing conversation.
            await get_conversation(db, conversation_id)

            active = self._registry.active_agent_session(conversation_id)
            if active is not None:
                raise ConversationBusyError(active)

            parent_session_id, parent_state, parent_project_ids = await self._find_parent(db, conversation_id)
        elif not preset_id:
            msg = "preset_id is required for new conversations"
            raise ValueError(msg)

        config = await self._resolve_config(
            db,
            preset_id=preset_id,
            config_override=config_override,
            workspace_id=workspace_id,
            project_ids=project_ids,
            parent_project_ids=parent_project_ids,
        )

        result = await launch_session(
            db=db,
            session_factory=self._session_factory,
            session_manager=self._session_manager,
            registry=self._registry,
            settings=self._settings,
            redis=self._redis,
            config=config,
            input_parts=input_parts or [],
            transport=transport,
            parent_session_id=parent_session_id,
            parent_state=parent_state,
            conversation_id=conversation_id,
            user_interactions=user_interactions,
            tool_results=tool_results,
        )

        # Apply metadata to new conversations.
        if conversation_id is None and metadata:
            with contextlib.suppress(ConversationNotFoundError):
                await update_conversation(db, result.conversation_id, ConversationUpdate(metadata=metadata))

        return result

    async def fork_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: str,
        preset_id: str,
        input_parts: Sequence[InputPart] | None = None,
        from_session_id: str | None = None,
        workspace_id: str | None = None,
        project_ids: list[str] | None = None,
        config_override: dict | None = None,
        metadata: dict | None = None,
        transport: Transport = Transport.SSE,
    ) -> LaunchResult:
        """Fork a new conversation from a session in an existing conversation.

        Raises
        ------
        ConversationNotFoundError: Source conversation not found.
        LookupError: Fork-point session not found.
        SessionNotInConversationError: Session doesn't belong to conversation.
        NoCommittedSessionError: No committed session to fork from.
        NoPresetError / WorkspaceNotFoundError / ProjectConflictError: Config errors.
        ValueError: Stream transport requested without Redis.
        """
        await get_conversation(db, conversation_id)

        parent_row, parent_state = await self._resolve_fork_point(db, conversation_id, from_session_id)

        config = await self._resolve_config(
            db,
            preset_id=preset_id,
            config_override=config_override,
            workspace_id=workspace_id,
            project_ids=project_ids,
            parent_project_ids=parent_row.project_ids,
        )

        result = await launch_session(
            db=db,
            session_factory=self._session_factory,
            session_manager=self._session_manager,
            registry=self._registry,
            settings=self._settings,
            redis=self._redis,
            config=config,
            input_parts=input_parts or [],
            transport=transport,
            parent_session_id=parent_row.session_id,
            parent_state=parent_state,
            conversation_id=uuid.uuid4().hex,
        )

        if metadata:
            with contextlib.suppress(ConversationNotFoundError):
                await update_conversation(db, result.conversation_id, ConversationUpdate(metadata=metadata))

        return result

    def interrupt_conversation(self, conversation_id: str) -> int:
        """Interrupt all active sessions in a conversation. Returns count."""
        sessions = self._registry.get_by_conversation(conversation_id)
        interrupted = 0
        for session in sessions:
            if session.streamer is not None:
                session.streamer.interrupt()
                interrupted += 1
        return interrupted

    def steer_conversation(self, conversation_id: str, text: str) -> str:
        """Steer the active agent session. Returns session_id.

        Raises
        ------
        NoActiveSessionError: No active agent session.
        SessionContextNotReadyError: Context not yet available.
        SteeringTextRequiredError: Empty steering text.
        """
        active = self._registry.active_agent_session(conversation_id)
        if active is None:
            raise NoActiveSessionError(conversation_id)

        self._send_steering(active, text)
        return active.session_id

    def get_active_session(self, conversation_id: str) -> RuntimeSession:
        """Get the active agent session for a conversation.

        Raises
        ------
        NoActiveSessionError: No active agent session.
        """
        active = self._registry.active_agent_session(conversation_id)
        if active is None:
            raise NoActiveSessionError(conversation_id)
        return active

    # -- Session operations ----------------------------------------------------

    async def execute_session(
        self,
        db: AsyncSession,
        *,
        preset_id: str,
        input_parts: Sequence[InputPart] | None = None,
        user_interactions: Sequence[UserInteraction] | None = None,
        tool_results: Sequence[ToolResult] | None = None,
        parent_session_id: str | None = None,
        fork: bool = False,
        workspace_id: str | None = None,
        project_ids: list[str] | None = None,
        config_override: dict | None = None,
        transport: Transport = Transport.SSE,
    ) -> LaunchResult:
        """Direct session execution with explicit parameters.

        Raises
        ------
        InputRequiredError: No input provided.
        NoPresetError / WorkspaceNotFoundError / ProjectConflictError: Config errors.
        LookupError: Parent session not found.
        ValueError: Stream transport requested without Redis.
        """
        if not input_parts and not user_interactions and not tool_results:
            raise InputRequiredError

        parent_state: SessionState | None = None
        parent_project_ids: list[str] | None = None

        if parent_session_id:
            parent_data = await self._session_manager.get_session(db, parent_session_id, include_state=True)
            parent_state = parent_data.get("state")
            parent_row = parent_data["index"]
            parent_project_ids = parent_row.project_ids

        config = await self._resolve_config(
            db,
            preset_id=preset_id,
            config_override=config_override,
            workspace_id=workspace_id,
            project_ids=project_ids,
            parent_project_ids=parent_project_ids,
        )

        conversation_id: str | None = None
        if parent_session_id and fork:
            conversation_id = uuid.uuid4().hex

        return await launch_session(
            db=db,
            session_factory=self._session_factory,
            session_manager=self._session_manager,
            registry=self._registry,
            settings=self._settings,
            redis=self._redis,
            config=config,
            input_parts=input_parts or [],
            transport=transport,
            parent_session_id=parent_session_id,
            parent_state=parent_state,
            conversation_id=conversation_id,
            user_interactions=user_interactions,
            tool_results=tool_results,
        )

    def interrupt_session(self, session_id: str) -> bool:
        """Interrupt a running session. Returns True if interrupted.

        Raises
        ------
        NoActiveSessionError: Session not found in registry.
        """
        live = self._registry.get(session_id)
        if live is None:
            raise NoActiveSessionError(session_id)

        if live.streamer is not None:
            live.streamer.interrupt()
            return True
        return False

    def steer_session(self, session_id: str, text: str) -> None:
        """Send steering input to a running session.

        Raises
        ------
        NoActiveSessionError: Session not found in registry.
        SessionContextNotReadyError: Context not yet available.
        SteeringTextRequiredError: Empty steering text.
        """
        live = self._registry.get(session_id)
        if live is None:
            raise NoActiveSessionError(session_id)

        self._send_steering(live, text)

    def get_session_status(self, session_id: str) -> tuple[SessionStatus, Transport | None, str | None]:
        """Check live session status from registry.

        Returns (status, transport, stream_key) if found in registry,
        or None if not active (caller should fall back to PG).
        """
        live = self._registry.get(session_id)
        if live is None:
            return None  # type: ignore[return-value]
        return SessionStatus.CREATED, live.transport, live.stream_key

    # -- Internal helpers ------------------------------------------------------

    async def _find_parent(
        self, db: AsyncSession, conversation_id: str
    ) -> tuple[str | None, SessionState | None, list[str] | None]:
        """Find latest committed session as parent for continuation."""
        parent_row = await self._session_manager.find_latest_committed_session(db, conversation_id)
        if parent_row is None:
            return None, None, None

        parent_data = await self._session_manager.get_session(db, parent_row.session_id, include_state=True)
        return (
            parent_row.session_id,
            parent_data.get("state"),
            parent_row.project_ids,
        )

    async def _resolve_fork_point(
        self,
        db: AsyncSession,
        conversation_id: str,
        from_session_id: str | None,
    ) -> tuple[SessionRow, SessionState | None]:
        """Find the session to fork from."""
        if from_session_id:
            parent_data = await self._session_manager.get_session(db, from_session_id, include_state=True)
            parent_row = parent_data["index"]
            if parent_row.conversation_id != conversation_id:
                raise SessionNotInConversationError(from_session_id, conversation_id)
            return parent_row, parent_data.get("state")

        latest = await self._session_manager.find_latest_committed_session(db, conversation_id)
        if latest is None:
            raise NoCommittedSessionError(conversation_id)

        parent_data = await self._session_manager.get_session(db, latest.session_id, include_state=True)
        return parent_data["index"], parent_data.get("state")

    async def _resolve_config(
        self,
        db: AsyncSession,
        *,
        preset_id: str | None,
        config_override: dict | None,
        workspace_id: str | None,
        project_ids: list[str] | None,
        parent_project_ids: list[str] | None,
    ):
        """Resolve execution config. Passes through domain exceptions."""
        override = ConfigOverride(**config_override) if config_override else None
        return await resolve_config(
            db,
            preset_id=preset_id,
            override=override,
            workspace_id=workspace_id,
            project_ids=project_ids,
            parent_project_ids=parent_project_ids,
        )

    @staticmethod
    def _send_steering(session: RuntimeSession, text: str) -> None:
        """Send steering text to a live session."""
        if not text:
            raise SteeringTextRequiredError

        if session.sdk_context is None:
            raise SessionContextNotReadyError(session.session_id)

        session.sdk_context.send_message(BusMessage(content=text, source="user"))
