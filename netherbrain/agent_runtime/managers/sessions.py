"""Session manager -- orchestrates session lifecycle across PG and state store.

The SessionManager is a process-level singleton initialised in the app lifespan.
It coordinates between three backends:

- **PostgreSQL**: Session and conversation index rows (queryable metadata)
- **State Store**: Large immutable blobs (context_state, message_history)
- **Registry**: In-memory live session references (interrupt, steering)

Individual methods accept an ``AsyncSession`` (DB) parameter so that database
access follows FastAPI's per-request dependency injection pattern.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import select, update

from netherbrain.agent_runtime.db.tables import Conversation as ConversationRow
from netherbrain.agent_runtime.db.tables import Session as SessionRow
from netherbrain.agent_runtime.models.enums import (
    ConversationStatus,
    SessionStatus,
    SessionType,
    Transport,
)
from netherbrain.agent_runtime.models.session import RunSummary, SessionState
from netherbrain.agent_runtime.store.base import DisplayMessages

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from netherbrain.agent_runtime.db.tables import Session as SessionRow
    from netherbrain.agent_runtime.registry import SessionRegistry
    from netherbrain.agent_runtime.store.base import StateStore


@dataclass
class SessionData:
    """Hydrated session data returned by ``SessionManager.get_session``.

    Replaces a loose dict to provide clear typing for callers.
    """

    index: SessionRow
    """The PG session row (always present)."""

    display_messages: DisplayMessages | None = None
    """Compressed display message chunks (always loaded, may be None)."""

    state: SessionState | None = None
    """Full SDK state (only loaded when ``include_state=True``)."""


class SessionManager:
    """Manages the full session lifecycle (create -> commit/fail).

    Instantiated once during app lifespan.  Stateless beyond its references
    to the state store and session registry.
    """

    def __init__(self, store: StateStore, registry: SessionRegistry) -> None:
        self._store = store
        self._registry = registry

    # -- Create ----------------------------------------------------------------

    async def create_session(
        self,
        db: AsyncSession,
        *,
        parent_session_id: str | None = None,
        conversation_id: str | None = None,
        preset_id: str | None = None,
        project_ids: list[str] | None = None,
        session_type: SessionType = SessionType.AGENT,
        transport: Transport = Transport.SSE,
        spawned_by: str | None = None,
        input_parts: list[dict[str, Any]] | None = None,
    ) -> SessionRow:
        """Create a new session with its PG index row and conversation.

        Conversation rules (from spec 01-session):
        - Root session (no parent): ``conversation_id = session_id`` (new conversation)
        - Continuation: ``conversation_id = parent.conversation_id``
        - Fork: caller provides a new ``conversation_id`` (or one is generated)
        - Async subagent: ``conversation_id = spawner.conversation_id``
        """
        session_id = uuid.uuid4().hex

        # Resolve conversation_id based on lineage rules.
        if parent_session_id is not None and conversation_id is None:
            # Continuation: inherit from parent.
            parent = await db.get(SessionRow, parent_session_id)
            if parent is None:
                msg = f"Parent session '{parent_session_id}' not found"
                raise ValueError(msg)
            conversation_id = parent.conversation_id
        elif conversation_id is None:
            # Root session: conversation_id = session_id.
            conversation_id = session_id

        # Ensure conversation index row exists.
        existing_conv = await db.get(ConversationRow, conversation_id)
        if existing_conv is None:
            conv = ConversationRow(
                conversation_id=conversation_id,
                status=ConversationStatus.ACTIVE,
            )
            db.add(conv)

        # Create session index row.
        session_row = SessionRow(
            session_id=session_id,
            parent_session_id=parent_session_id,
            project_ids=project_ids or [],
            status=SessionStatus.CREATED,
            session_type=session_type,
            transport=transport,
            conversation_id=conversation_id,
            spawned_by=spawned_by,
            preset_id=preset_id,
            input=input_parts,
        )
        db.add(session_row)
        await db.commit()
        await db.refresh(session_row)

        logger.info(
            "Session created: {} (conversation={}, parent={})",
            session_id,
            conversation_id,
            parent_session_id,
        )
        return session_row

    # -- Commit ----------------------------------------------------------------

    async def commit_session(
        self,
        db: AsyncSession,
        session_id: str,
        *,
        state: SessionState,
        final_message: str | None = None,
        deferred_tools: dict | None = None,
        run_summary: RunSummary | None = None,
        display_messages: DisplayMessages | None = None,
        status: SessionStatus = SessionStatus.COMMITTED,
    ) -> SessionRow:
        """Commit a session: write state to store, update PG index.

        This is called after successful execution.  The session is immutable
        after commit -- no further writes to its state.
        """
        if status not in (SessionStatus.COMMITTED, SessionStatus.AWAITING_TOOL_RESULTS):
            msg = f"Cannot commit with status '{status}'; use fail_session for failures"
            raise ValueError(msg)

        # Write SDK state blob to state store.
        await self._store.write_state(session_id, state)

        # Write display messages (optional, separate file).
        if display_messages is not None:
            await self._store.write_display_messages(session_id, display_messages)

        # Update PG index (status, final_message, deferred_tools, run_summary).
        values: dict[str, Any] = {"status": status}
        if final_message is not None:
            values["final_message"] = final_message
        if deferred_tools is not None:
            values["deferred_tools"] = deferred_tools
        if run_summary is not None:
            values["run_summary"] = run_summary.model_dump()

        stmt = update(SessionRow).where(SessionRow.session_id == session_id).values(**values)
        await db.execute(stmt)
        await db.commit()

        # Unregister from in-memory registry.
        self._registry.unregister(session_id)

        row = await db.get(SessionRow, session_id)
        logger.info("Session committed: {} (status={})", session_id, status)
        return row  # type: ignore[return-value]

    # -- Fail ------------------------------------------------------------------

    async def fail_session(
        self,
        db: AsyncSession,
        session_id: str,
    ) -> None:
        """Mark a session as failed.  No state is written to the store."""
        stmt = update(SessionRow).where(SessionRow.session_id == session_id).values(status=SessionStatus.FAILED)
        await db.execute(stmt)
        await db.commit()

        self._registry.unregister(session_id)
        logger.info("Session failed: {}", session_id)

    # -- Read ------------------------------------------------------------------

    async def get_session(
        self,
        db: AsyncSession,
        session_id: str,
        *,
        include_state: bool = False,
    ) -> SessionData:
        """Get session index from PG, hydrated with display messages.

        Returns a ``SessionData`` with ``index`` (always), ``display_messages``
        (always, may be None), and ``state`` (optional).
        """
        row = await db.get(SessionRow, session_id)
        if row is None:
            msg = f"Session '{session_id}' not found"
            raise LookupError(msg)

        display = await self._store.read_display_messages(session_id)

        state: SessionState | None = None
        if include_state:
            try:
                state = await self._store.read_state(session_id)
            except FileNotFoundError:
                state = None

        return SessionData(index=row, display_messages=display, state=state)

    async def list_sessions(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SessionRow]:
        """List sessions for a conversation, ordered by creation time."""
        stmt = (
            select(SessionRow)
            .where(SessionRow.conversation_id == conversation_id)
            .order_by(SessionRow.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # -- Parent lookup ---------------------------------------------------------

    async def find_latest_committed_session(
        self,
        db: AsyncSession,
        conversation_id: str,
    ) -> SessionRow | None:
        """Find the latest committed (or awaiting_tool_results) session.

        Used by ``/conversations/run`` (continue) and ``/conversations/fork``
        to locate the parent session for state restoration.
        """
        stmt = (
            select(SessionRow)
            .where(
                SessionRow.conversation_id == conversation_id,
                SessionRow.status.in_([
                    SessionStatus.COMMITTED,
                    SessionStatus.AWAITING_TOOL_RESULTS,
                ]),
            )
            .order_by(SessionRow.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # -- Turns -----------------------------------------------------------------

    async def get_conversation_turns(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        include_display: bool = False,
    ) -> list[dict]:
        """Get input/output pairs for all committed sessions in a conversation.

        Returns a list of dicts with ``input``, ``final_message``, and
        ``session_id`` in chronological order.  Sessions without final_message
        are included (they represent in-progress or failed turns).

        When ``include_display`` is True, each turn additionally includes
        ``display_messages`` loaded from the State Store.
        """
        stmt = (
            select(
                SessionRow.session_id,
                SessionRow.input,
                SessionRow.final_message,
                SessionRow.created_at,
            )
            .where(
                SessionRow.conversation_id == conversation_id,
                SessionRow.status.in_([
                    SessionStatus.COMMITTED,
                    SessionStatus.AWAITING_TOOL_RESULTS,
                ]),
            )
            .order_by(SessionRow.created_at.asc())
        )
        result = await db.execute(stmt)
        turns = []
        for row in result.all():
            turn: dict = {
                "session_id": row.session_id,
                "input": row.input,
                "final_message": row.final_message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            if include_display:
                turn["display_messages"] = await self._store.read_display_messages(row.session_id)
            turns.append(turn)
        return turns

    # -- Startup recovery ------------------------------------------------------

    @staticmethod
    async def recover_orphaned_sessions(db: AsyncSession) -> int:
        """Mark orphaned sessions (status=created) as failed.

        Called once at startup to reconcile PG with the empty registry after
        a crash or restart.  Returns the number of sessions recovered.
        """
        stmt = update(SessionRow).where(SessionRow.status == SessionStatus.CREATED).values(status=SessionStatus.FAILED)
        result = await db.execute(stmt)
        await db.commit()
        count = result.rowcount  # type: ignore[assignment]
        if count > 0:
            logger.warning("Startup recovery: marked {} orphaned sessions as failed", count)
        return count
