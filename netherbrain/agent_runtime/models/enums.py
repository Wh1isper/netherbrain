"""Shared enumerations used across the agent runtime.

Note: Event types come from ``ag_ui.core.EventType``. This module
does NOT define event types -- see ``models/events.py`` for the
event layer.
"""

from __future__ import annotations

from enum import StrEnum

# -- Session -----------------------------------------------------------------


class SessionStatus(StrEnum):
    """Durable session status persisted in PG."""

    CREATED = "created"
    COMMITTED = "committed"
    AWAITING_TOOL_RESULTS = "awaiting_tool_results"
    FAILED = "failed"
    ARCHIVED = "archived"


class SessionType(StrEnum):
    AGENT = "agent"
    ASYNC_SUBAGENT = "async_subagent"


class Transport(StrEnum):
    SSE = "sse"
    STREAM = "stream"


# -- Conversation ------------------------------------------------------------


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


# -- Environment -------------------------------------------------------------


class EnvironmentMode(StrEnum):
    LOCAL = "local"
    SANDBOX = "sandbox"


# -- Mailbox -----------------------------------------------------------------


class MailboxSourceType(StrEnum):
    SUBAGENT_RESULT = "subagent_result"
    SUBAGENT_FAILED = "subagent_failed"


# -- Input -------------------------------------------------------------------


class ContentMode(StrEnum):
    """Delivery mode for non-text input parts."""

    FILE = "file"
    INLINE = "inline"


class InputPartType(StrEnum):
    """Content part type in user input."""

    TEXT = "text"
    URL = "url"
    FILE = "file"
    BINARY = "binary"


# -- Auth / Multi-tenancy ---------------------------------------------------


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"
