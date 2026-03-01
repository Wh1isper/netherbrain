"""In-process session registry.

Tracks active (running) sessions with live object references for direct
control (interrupt, steering).  Ephemeral -- empty on process restart.
All durable state lives in PostgreSQL.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from netherbrain.agent_runtime.context import RuntimeSession
    from netherbrain.agent_runtime.models.enums import Transport


class ShuttingDownError(RuntimeError):
    """Raised when attempting to register a session during shutdown."""


class SessionRegistry:
    """Thread-safe registry of currently executing sessions.

    In the single-instance architecture, the API handler and agent runner share
    the same process, so direct method calls replace any external broker.

    The registry also provides a drain mechanism for graceful shutdown:
    ``wait_until_drained`` blocks until all sessions have been unregistered.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeSession] = {}
        self._drain_event = asyncio.Event()
        self._drain_event.set()  # Starts "drained" (no sessions).
        self._shutting_down = False

    # -- Mutation --------------------------------------------------------------

    def register(self, session: RuntimeSession) -> None:
        """Register a session.  Raises ``RuntimeError`` if shutting down."""
        if self._shutting_down:
            raise ShuttingDownError
        logger.debug("Registry: register session {} (transport={})", session.session_id, session.transport)
        self._sessions[session.session_id] = session
        self._drain_event.clear()

    def unregister(self, session_id: str) -> RuntimeSession | None:
        session = self._sessions.pop(session_id, None)
        if session:
            logger.debug("Registry: unregister session {}", session_id)
        if not self._sessions:
            self._drain_event.set()
        return session

    # -- Query -----------------------------------------------------------------

    def get(self, session_id: str) -> RuntimeSession | None:
        return self._sessions.get(session_id)

    def get_by_conversation(self, conversation_id: str) -> list[RuntimeSession]:
        """Return all active sessions belonging to a conversation."""
        return [s for s in self._sessions.values() if s.conversation_id == conversation_id]

    def active_agent_session(self, conversation_id: str) -> RuntimeSession | None:
        """Return the single active agent-type session for a conversation, if any."""
        from netherbrain.agent_runtime.models.enums import SessionType

        for s in self._sessions.values():
            if s.conversation_id == conversation_id and s.session_type == SessionType.AGENT:
                return s
        return None

    def all_sessions(self) -> list[RuntimeSession]:
        """Return a snapshot of all active sessions."""
        return list(self._sessions.values())

    def by_transport(self, transport: Transport) -> list[RuntimeSession]:
        """Return all active sessions using the given transport."""
        return [s for s in self._sessions.values() if s.transport == transport]

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    # -- Lifecycle -------------------------------------------------------------

    def begin_shutdown(self) -> None:
        """Mark the registry as shutting down.  New registrations are refused."""
        self._shutting_down = True
        logger.info("Registry: shutdown initiated, refusing new sessions")
        if not self._sessions:
            self._drain_event.set()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    # -- Control ---------------------------------------------------------------

    def interrupt_all(self) -> int:
        """Send interrupt to all active sessions.

        Intended for explicit ``/interrupt`` API calls and as a last-resort
        during forced shutdown.  Normal graceful shutdown should use
        ``begin_shutdown`` + ``wait_until_drained`` instead.

        Returns the number of sessions that had a live streamer reference.
        """
        count = 0
        for session in self._sessions.values():
            if session.streamer is not None:
                session.streamer.interrupt()
                count += 1
                logger.info("Registry: interrupted session {}", session.session_id)
        return count

    async def wait_until_drained(self, timeout: float | None = None) -> bool:
        """Wait until all sessions have been unregistered (drained).

        Returns ``True`` if the registry is empty, ``False`` if *timeout*
        expired with sessions still active.  Called during graceful shutdown
        to let in-flight executions finish before tearing down infrastructure.
        """
        if not self._sessions:
            return True
        try:
            await asyncio.wait_for(self._drain_event.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "Registry: drain timed out after {}s with {} sessions still active",
                timeout,
                len(self._sessions),
            )
            return False
        else:
            return True
