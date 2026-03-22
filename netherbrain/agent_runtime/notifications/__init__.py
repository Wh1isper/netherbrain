"""Notification events for real-time WebSocket push.

Lightweight dataclasses representing state changes that are serialized
to JSON and published via Redis Pub/Sub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class SessionStarted:
    """A new session began executing."""

    conversation_id: str
    session_id: str
    session_type: str
    transport: str
    type: str = field(default="session_started", init=False)
    timestamp: str = field(default_factory=_now_iso)


@dataclass(slots=True)
class SessionCompleted:
    """A session committed successfully."""

    conversation_id: str
    session_id: str
    session_type: str
    final_message_preview: str | None = None
    type: str = field(default="session_completed", init=False)
    timestamp: str = field(default_factory=_now_iso)


@dataclass(slots=True)
class SessionFailed:
    """A session failed."""

    conversation_id: str
    session_id: str
    session_type: str
    error: str | None = None
    type: str = field(default="session_failed", init=False)
    timestamp: str = field(default_factory=_now_iso)


@dataclass(slots=True)
class MailboxUpdated:
    """A new message was posted to a conversation mailbox."""

    conversation_id: str
    message_id: str
    source_session_id: str
    source_type: str
    subagent_name: str
    pending_count: int
    type: str = field(default="mailbox_updated", init=False)
    timestamp: str = field(default_factory=_now_iso)


@dataclass(slots=True)
class ConversationUpdated:
    """Conversation metadata changed."""

    conversation_id: str
    changes: list[str]
    type: str = field(default="conversation_updated", init=False)
    timestamp: str = field(default_factory=_now_iso)


NotificationEvent = SessionStarted | SessionCompleted | SessionFailed | MailboxUpdated | ConversationUpdated
