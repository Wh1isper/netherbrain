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


class UsageSummary(BaseModel):
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_requests: int = 0


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
