"""Session and conversation data models.

Domain objects from spec/agent_runtime/01-session.md.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from netherbrain.agent_runtime.models.enums import (
    ConversationStatus,
    MailboxSourceType,
    SessionStatus,
    SessionType,
    Transport,
)

# -- Run summary -------------------------------------------------------------


class ModelUsageSummary(BaseModel):
    """Token usage for a single model (stored in PG JSONB).

    Fields aligned with ``pydantic_ai.RunUsage`` naming conventions.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0


class UsageSummary(BaseModel):
    """Aggregated token usage by model_id (stored in PG JSONB).

    Different models have different costs, so usage is tracked per model.
    """

    model_usages: dict[str, ModelUsageSummary] = Field(default_factory=dict)


class RunSummary(BaseModel):
    duration_ms: int = 0
    usage: UsageSummary = Field(default_factory=UsageSummary)


# -- Session -----------------------------------------------------------------


class SessionMetadata(BaseModel):
    """Indexed fields stored alongside the session in PG."""

    session_type: SessionType = SessionType.AGENT
    transport: Transport = Transport.SSE
    conversation_id: str = ""
    spawned_by: str | None = None
    preset_id: str | None = None


class SessionIndex(BaseModel):
    """Session index row (PG).  Lightweight, queryable."""

    session_id: str
    parent_session_id: str | None = None
    project_ids: list[str] = Field(
        default_factory=list, description="Ordered project references for this session's environment"
    )
    status: SessionStatus = SessionStatus.CREATED
    run_summary: RunSummary | None = None
    metadata: SessionMetadata = Field(default_factory=SessionMetadata)
    created_at: datetime | None = None


class SessionState(BaseModel):
    """Full session state blob written to the state store."""

    context_state: dict = Field(default_factory=dict, description="SDK ResumableState export")
    message_history: list = Field(default_factory=list, description="pydantic-ai ModelMessage list")
    environment_state: dict = Field(default_factory=dict, description="Environment resource snapshot")


# -- Deferred tools (display data for AWAITING_TOOL_RESULTS) -----------------


class DeferredToolCall(BaseModel):
    """A single pending tool call awaiting external input."""

    tool_call_id: str
    tool_name: str
    args: str = ""


class DeferredTools(BaseModel):
    """Simplified representation of pending tool requests.

    Stored as JSONB on the session row so clients can render
    approval UI without loading the full SDK context_state.
    """

    calls: list[DeferredToolCall] = Field(
        default_factory=list,
        description="Tools requiring external execution results",
    )
    approvals: list[DeferredToolCall] = Field(
        default_factory=list,
        description="Tools requiring human-in-the-loop approval",
    )


# -- Conversation ------------------------------------------------------------


class ConversationIndex(BaseModel):
    """Conversation index row (PG)."""

    conversation_id: str
    title: str | None = None
    default_preset_id: str | None = None
    metadata: dict | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None


# -- Mailbox -----------------------------------------------------------------


class MailboxMessage(BaseModel):
    """A single message in the conversation mailbox (PG)."""

    message_id: str
    conversation_id: str
    source_session_id: str
    source_type: MailboxSourceType
    subagent_name: str
    created_at: datetime | None = None
    delivered_to: str | None = None
