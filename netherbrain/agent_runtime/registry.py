"""In-process session registry.

Tracks active (running) sessions with live object references for direct
control (interrupt, steering).  Ephemeral -- empty on process restart.
All durable state lives in PostgreSQL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from netherbrain.agent_runtime.context import RuntimeSession


class SessionRegistry:
    """Thread-safe registry of currently executing sessions.

    In the single-instance architecture, the API handler and agent runner share
    the same process, so direct method calls replace any external broker.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeSession] = {}

    # -- Mutation --------------------------------------------------------------

    def register(self, session: RuntimeSession) -> None:
        logger.debug("Registry: register session {}", session.session_id)
        self._sessions[session.session_id] = session

    def unregister(self, session_id: str) -> RuntimeSession | None:
        session = self._sessions.pop(session_id, None)
        if session:
            logger.debug("Registry: unregister session {}", session_id)
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

    @property
    def active_count(self) -> int:
        return len(self._sessions)
