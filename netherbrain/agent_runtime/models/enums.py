"""Shared enumerations used across the agent runtime."""

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


class ShellMode(StrEnum):
    LOCAL = "local"
    DOCKER = "docker"


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


# -- Events ------------------------------------------------------------------


class EventType(StrEnum):
    """Protocol event types emitted during execution."""

    # Lifecycle
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"

    # Content
    MESSAGE_START = "message_start"
    CONTENT_DELTA = "content_delta"
    CONTENT_DONE = "content_done"
    MESSAGE_END = "message_end"

    # Tool
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_ARGS_DELTA = "tool_call_args_delta"
    TOOL_CALL_RESULT = "tool_call_result"
    TOOL_CALL_END = "tool_call_end"

    # Subagent
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"

    # Context
    COMPACT_STARTED = "compact_started"
    COMPACT_COMPLETED = "compact_completed"
    HANDOFF_COMPLETED = "handoff_completed"

    # Control
    INTERRUPT_RECEIVED = "interrupt_received"
    STEERING_INJECTED = "steering_injected"
    USAGE_SNAPSHOT = "usage_snapshot"
