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

from loguru import logger
from sqlalchemy import update
from ya_agent_sdk.context import BusMessage

from netherbrain.agent_runtime.context import RuntimeSession
from netherbrain.agent_runtime.db.tables import MailboxMessage
from netherbrain.agent_runtime.db.tables import Session as SessionRow
from netherbrain.agent_runtime.execution.launch import LaunchResult, launch_session
from netherbrain.agent_runtime.execution.mailbox_prompt import (
    MailboxMessageWithContent,
    render_mailbox_prompt,
)
from netherbrain.agent_runtime.execution.resolver import (
    ConfigOverride,
    resolve_config,
)
from netherbrain.agent_runtime.managers.conversations import (
    ConversationNotFoundError,
    get_conversation,
    update_conversation,
)
from netherbrain.agent_runtime.managers.mailbox import (
    count_pending,
    drain_undelivered,
)
from netherbrain.agent_runtime.models.api import ConversationUpdate
from netherbrain.agent_runtime.models.enums import (
    EnvironmentMode,
    InputPartType,
    MailboxSourceType,
    SessionStatus,
    SessionType,
    Transport,
)
from netherbrain.agent_runtime.models.input import InputPart, ToolResult, UserInteraction

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from netherbrain.agent_runtime.managers.sessions import SessionManager
    from netherbrain.agent_runtime.models.api import ExternalToolSpec
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


class EmptyMailboxError(ValueError):
    """No pending mailbox messages for the conversation."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"No pending mailbox messages for conversation '{conversation_id}'")


class NoDefaultPresetError(ValueError):
    """No preset_id provided and conversation has no default_preset_id."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"No preset_id provided and conversation '{conversation_id}' has no default_preset_id")


# ---------------------------------------------------------------------------
# ExecutionManager
# ---------------------------------------------------------------------------


def _empty_session_state():
    """Lazy import to avoid circular dependency at module level."""
    from netherbrain.agent_runtime.models.session import SessionState

    return SessionState()


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
        user_id: str | None = None,
        external_tools: Sequence[ExternalToolSpec] | None = None,
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
            user_id=user_id,
            user_interactions=user_interactions,
            tool_results=tool_results,
            external_tools=external_tools,
            execution_manager=self,
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
        user_id: str | None = None,
        external_tools: Sequence[ExternalToolSpec] | None = None,
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
            user_id=user_id,
            external_tools=external_tools,
            execution_manager=self,
        )

        if metadata:
            with contextlib.suppress(ConversationNotFoundError):
                await update_conversation(db, result.conversation_id, ConversationUpdate(metadata=metadata))

        return result

    async def prepare_fork(
        self,
        db: AsyncSession,
        *,
        conversation_id: str,
        from_session_id: str | None = None,
        metadata: dict | None = None,
        user_id: str | None = None,
    ) -> str:
        """Create a forked conversation without launching execution.

        Copies the fork-point session's state into a new conversation so
        that the next ``run_conversation`` call on the new conversation
        resumes from the fork point.

        Returns the new conversation_id.

        Raises
        ------
        ConversationNotFoundError: Source conversation not found.
        LookupError: Fork-point session not found.
        SessionNotInConversationError: Session doesn't belong to conversation.
        NoCommittedSessionError: No committed session to fork from.
        """
        source_conv = await get_conversation(db, conversation_id)

        parent_row, parent_state = await self._resolve_fork_point(db, conversation_id, from_session_id)

        new_conversation_id = uuid.uuid4().hex

        # Create a new session in the new conversation, linked to the parent.
        session_row = await self._session_manager.create_session(
            db,
            parent_session_id=parent_row.session_id,
            conversation_id=new_conversation_id,
            user_id=user_id,
            preset_id=parent_row.preset_id,
            project_ids=parent_row.project_ids,
        )

        # Immediately commit with the parent's state so the new conversation
        # has a committed session that run_conversation can continue from.
        await self._session_manager.commit_session(
            db,
            session_row.session_id,
            state=parent_state or _empty_session_state(),
        )

        # Copy display messages from parent session.
        store = self._session_manager._store
        parent_display = await store.read_display_messages(parent_row.session_id)
        if parent_display is not None:
            await store.write_display_messages(session_row.session_id, parent_display)

        # Set metadata (including workspace_id) and inherit title/preset.
        update_fields = ConversationUpdate(
            default_preset_id=source_conv.default_preset_id or parent_row.preset_id,
        )
        if metadata:
            update_fields.metadata = metadata
        if source_conv.title:
            update_fields.title = f"{source_conv.title} (fork)"
        await update_conversation(db, new_conversation_id, update_fields)

        logger.info(
            "Prepared fork: {} -> {} (parent_session={})",
            conversation_id,
            new_conversation_id,
            parent_row.session_id,
        )
        return new_conversation_id

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

    async def fire_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: str,
        preset_id: str | None = None,
        input_parts: Sequence[InputPart] | None = None,
        user_interactions: Sequence[UserInteraction] | None = None,
        tool_results: Sequence[ToolResult] | None = None,
        workspace_id: str | None = None,
        project_ids: list[str] | None = None,
        config_override: dict | None = None,
        transport: Transport = Transport.STREAM,
        user_id: str | None = None,
        external_tools: Sequence[ExternalToolSpec] | None = None,
    ) -> LaunchResult:
        """Drain mailbox and launch a continuation session.

        Raises
        ------
        ConversationNotFoundError: Conversation not found.
        ConversationBusyError: Active agent session exists.
        EmptyMailboxError: No pending mailbox messages.
        NoDefaultPresetError: No preset resolvable.
        NoPresetError / WorkspaceNotFoundError / ProjectConflictError: Config errors.
        ValueError: Stream transport requested without Redis.
        """
        # Validate conversation exists.
        conv = await get_conversation(db, conversation_id)

        # Check no active agent session.
        active = self._registry.active_agent_session(conversation_id)
        if active is not None:
            raise ConversationBusyError(active)

        # Check mailbox has pending messages.
        pending = await count_pending(db, conversation_id=conversation_id)
        if pending == 0:
            raise EmptyMailboxError(conversation_id)

        # Resolve preset: explicit > conversation default.
        effective_preset_id = preset_id or conv.default_preset_id
        if not effective_preset_id:
            raise NoDefaultPresetError(conversation_id)

        # Find parent session for continuation.
        parent_session_id, parent_state, parent_project_ids = await self._find_parent(db, conversation_id)

        # Resolve config.
        config = await self._resolve_config(
            db,
            preset_id=effective_preset_id,
            config_override=config_override,
            workspace_id=workspace_id,
            project_ids=project_ids,
            parent_project_ids=parent_project_ids,
        )

        # Drain mailbox (atomic claim with temporary marker).
        # We use a temporary ID; will update to real session ID after launch.
        temp_claim = uuid.uuid4().hex
        drained = await drain_undelivered(db, conversation_id=conversation_id, delivered_to=temp_claim)

        if not drained:
            raise EmptyMailboxError(conversation_id)

        # Load final_message for each drained source session.
        enriched: list[MailboxMessageWithContent] = []
        for msg in drained:
            source_row = await db.get(SessionRow, msg.source_session_id)
            enriched.append(
                MailboxMessageWithContent(
                    message_id=msg.message_id,
                    source_session_id=msg.source_session_id,
                    source_type=MailboxSourceType(msg.source_type),
                    subagent_name=msg.subagent_name,
                    final_message=source_row.final_message if source_row else None,
                )
            )

        # Build user text from input parts (if any).
        user_text: str | None = None
        if input_parts:
            text_parts = [p.text for p in input_parts if p.text]
            user_text = "\n".join(text_parts) if text_parts else None

        # Render mailbox prompt.
        mailbox_prompt = render_mailbox_prompt(enriched, user_input=user_text)

        # Build input for continuation (mailbox prompt as text).
        continuation_input = [InputPart(type=InputPartType.TEXT, text=mailbox_prompt)]

        # Launch continuation session.
        # If launch fails, revert the mailbox claim so messages can be
        # re-delivered on the next fire attempt.
        try:
            result = await launch_session(
                db=db,
                session_factory=self._session_factory,
                session_manager=self._session_manager,
                registry=self._registry,
                settings=self._settings,
                redis=self._redis,
                config=config,
                input_parts=continuation_input,
                transport=transport,
                parent_session_id=parent_session_id,
                parent_state=parent_state,
                conversation_id=conversation_id,
                user_id=user_id,
                user_interactions=user_interactions,
                tool_results=tool_results,
                external_tools=external_tools,
                execution_manager=self,
            )
        except Exception:
            # Revert claim: set delivered_to back to NULL.
            await db.execute(
                update(MailboxMessage).where(MailboxMessage.delivered_to == temp_claim).values(delivered_to=None)
            )
            await db.commit()
            raise

        # Update drained messages: delivered_to = real session ID.
        try:
            await db.execute(
                update(MailboxMessage)
                .where(MailboxMessage.delivered_to == temp_claim)
                .values(delivered_to=result.session_id)
            )
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to update mailbox delivered_to for conversation %s (temp_claim=%s, session=%s)",
                conversation_id,
                temp_claim,
                result.session_id,
            )

        return result

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
        user_id: str | None = None,
        external_tools: Sequence[ExternalToolSpec] | None = None,
        # Subagent classification (used by spawn_delegate, not external API)
        session_type: SessionType = SessionType.AGENT,
        spawned_by: str | None = None,
        subagent_name: str | None = None,
        # Environment inheritance (explicit override for subagent config resolution)
        parent_environment_mode: EnvironmentMode | None = None,
        parent_container_id: str | None = None,
        parent_container_workdir: str | None = None,
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
            parent_state = parent_data.state
            parent_row = parent_data.index
            parent_project_ids = parent_row.project_ids

        config = await self._resolve_config(
            db,
            preset_id=preset_id,
            config_override=config_override,
            workspace_id=workspace_id,
            project_ids=project_ids,
            parent_project_ids=parent_project_ids,
            parent_environment_mode=parent_environment_mode,
            parent_container_id=parent_container_id,
            parent_container_workdir=parent_container_workdir,
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
            user_id=user_id,
            user_interactions=user_interactions,
            tool_results=tool_results,
            session_type=session_type,
            spawned_by=spawned_by,
            subagent_name=subagent_name,
            external_tools=external_tools,
            execution_manager=self,
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

    def get_session_status(self, session_id: str) -> tuple[SessionStatus, Transport | None, str | None] | None:
        """Check live session status from registry.

        Returns (status, transport, stream_key) if found in registry,
        or None if not active (caller should fall back to PG).
        """
        live = self._registry.get(session_id)
        if live is None:
            return None
        return SessionStatus.CREATED, live.transport, live.stream_key

    async def get_session_status_full(
        self, session_id: str, db: AsyncSession
    ) -> tuple[SessionStatus, Transport | None, str | None]:
        """Get session status: registry first, PG fallback.

        Raises ``LookupError`` if session not found anywhere.
        """
        live = self.get_session_status(session_id)
        if live is not None:
            return live

        row = await db.get(SessionRow, session_id)
        if row is None:
            raise LookupError(session_id)
        return SessionStatus(row.status), Transport(row.transport), None

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
            parent_data.state,
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
            parent_row = parent_data.index
            if parent_row.conversation_id != conversation_id:
                raise SessionNotInConversationError(from_session_id, conversation_id)
            return parent_row, parent_data.state

        latest = await self._session_manager.find_latest_committed_session(db, conversation_id)
        if latest is None:
            raise NoCommittedSessionError(conversation_id)

        parent_data = await self._session_manager.get_session(db, latest.session_id, include_state=True)
        return parent_data.index, parent_data.state

    async def _resolve_config(
        self,
        db: AsyncSession,
        *,
        preset_id: str | None,
        config_override: dict | None,
        workspace_id: str | None,
        project_ids: list[str] | None,
        parent_project_ids: list[str] | None,
        parent_environment_mode: EnvironmentMode | None = None,
        parent_container_id: str | None = None,
        parent_container_workdir: str | None = None,
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
            parent_environment_mode=parent_environment_mode,
            parent_container_id=parent_container_id,
            parent_container_workdir=parent_container_workdir,
        )

    @staticmethod
    def _send_steering(session: RuntimeSession, text: str) -> None:
        """Send steering text to a live session."""
        if not text:
            raise SteeringTextRequiredError

        if session.sdk_context is None:
            raise SessionContextNotReadyError(session.session_id)

        session.sdk_context.send_message(BusMessage(content=text, source="user"))
