"""State store interface for session persistence.

The state store handles large, immutable blobs (session state) that are
written once at commit time and read on restore.  The interface is async
to support both local filesystem and remote (S3) backends.

PostgreSQL stores the lightweight session index (including input and
final_message for display); the state store holds the heavy SDK state
payload.  See spec/agent_runtime/01-session.md for the persistence topology.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from netherbrain.agent_runtime.models.session import SessionState


@runtime_checkable
class StateStore(Protocol):
    """Async protocol for reading and writing session state blobs.

    Storage layout (keyed by session_id):
        {root}/sessions/{session_id}/state.json
    """

    async def write_state(self, session_id: str, state: SessionState) -> None:
        """Write session state (context_state, message_history, environment_state)."""
        ...

    async def read_state(self, session_id: str) -> SessionState:
        """Read session state.  Raises ``FileNotFoundError`` if not found."""
        ...

    async def exists(self, session_id: str) -> bool:
        """Check whether state exists for the given session."""
        ...

    async def delete(self, session_id: str) -> None:
        """Delete all stored data for a session.  No-op if not found."""
        ...
