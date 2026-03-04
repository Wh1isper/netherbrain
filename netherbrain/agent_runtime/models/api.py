"""API request / response schemas for CRUD endpoints.

These thin schemas sit between HTTP and the ORM layer.  They are separate
from the domain models in ``preset.py`` / ``session.py`` / ``workspace.py``
because they serve a different purpose:

- **Create** schemas validate user input and provide defaults.
- **Update** schemas allow partial updates via ``exclude_unset``.
- **Response** schemas serialize ORM rows via ``from_attributes``.

Nested structured types (``ModelPreset``, ``ToolsetSpec``, ...) are reused
from the domain models for validation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from netherbrain.agent_runtime.models.enums import (
    ConversationStatus,
    MailboxSourceType,
    SessionStatus,
    SessionType,
    Transport,
    UserRole,
)
from netherbrain.agent_runtime.models.input import InputPart, ToolResult, UserInteraction
from netherbrain.agent_runtime.models.preset import (
    EnvironmentSpec,
    McpServerSpec,
    ModelPreset,
    SubagentSpec,
    ToolConfigSpec,
    ToolsetSpec,
)
from netherbrain.agent_runtime.models.session import DeferredTools, RunSummary

# ---------------------------------------------------------------------------
# Preset
# ---------------------------------------------------------------------------


class PresetCreate(BaseModel):
    """Input for creating a new agent preset."""

    preset_id: str | None = Field(default=None, description="Optional; auto-generated UUID if omitted.")
    name: str
    description: str | None = None
    model: ModelPreset
    system_prompt: str
    toolsets: list[ToolsetSpec] = Field(default_factory=list)
    environment: EnvironmentSpec = Field(default_factory=EnvironmentSpec)
    tool_config: ToolConfigSpec = Field(default_factory=ToolConfigSpec)
    subagents: SubagentSpec = Field(default_factory=SubagentSpec)
    mcp_servers: list[McpServerSpec] = Field(default_factory=list)
    is_default: bool = False


class PresetUpdate(BaseModel):
    """Partial update -- only fields explicitly set by the caller are applied.

    Routers should use ``body.model_dump(exclude_unset=True)`` to extract
    only the provided fields.
    """

    name: str | None = None
    description: str | None = None
    model: ModelPreset | None = None
    system_prompt: str | None = None
    toolsets: list[ToolsetSpec] | None = None
    environment: EnvironmentSpec | None = None
    tool_config: ToolConfigSpec | None = None
    subagents: SubagentSpec | None = None
    mcp_servers: list[McpServerSpec] | None = None
    is_default: bool | None = None


class PresetResponse(BaseModel):
    """Serialized preset returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    preset_id: str
    name: str
    description: str | None = None
    model: ModelPreset
    system_prompt: str
    toolsets: list[ToolsetSpec]
    environment: EnvironmentSpec
    tool_config: ToolConfigSpec
    subagents: SubagentSpec
    mcp_servers: list[McpServerSpec]
    is_default: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class WorkspaceCreate(BaseModel):
    """Input for creating a new workspace."""

    workspace_id: str | None = Field(default=None, description="Optional; auto-generated UUID if omitted.")
    name: str | None = None
    projects: list[str] = Field(default_factory=list, description="Ordered project IDs; first = default.")
    metadata: dict | None = None


class WorkspaceUpdate(BaseModel):
    """Partial workspace update."""

    name: str | None = None
    projects: list[str] | None = None
    metadata: dict | None = None


class WorkspaceResponse(BaseModel):
    """Serialized workspace returned to clients."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    workspace_id: str
    name: str | None = None
    projects: list[str]
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class ConversationResponse(BaseModel):
    """Serialized conversation returned to clients.

    The ORM attribute is ``metadata_`` (to avoid shadowing the Pydantic
    reserved name), so we use ``validation_alias`` to read it correctly.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    conversation_id: str
    user_id: str
    title: str | None = None
    default_preset_id: str | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime


class LatestSessionInfo(BaseModel):
    """Summary of the latest committed session in a conversation."""

    session_id: str
    status: SessionStatus
    session_type: SessionType
    project_ids: list[str]
    preset_id: str | None = None
    created_at: datetime


class MailboxSummary(BaseModel):
    """Mailbox summary for a conversation."""

    pending_count: int


class ConversationDetailResponse(ConversationResponse):
    """Enriched conversation response with session and mailbox info."""

    latest_session: LatestSessionInfo | None = None
    active_session: ActiveSessionInfo | None = None
    mailbox: MailboxSummary | None = None


class ConversationUpdate(BaseModel):
    """Partial conversation update."""

    title: str | None = None
    default_preset_id: str | None = None
    metadata: dict | None = None
    status: ConversationStatus | None = None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    """Serialized session index row returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    parent_session_id: str | None = None
    project_ids: list[str]
    status: SessionStatus
    run_summary: RunSummary | None = None
    session_type: SessionType
    transport: Transport
    conversation_id: str
    spawned_by: str | None = None
    preset_id: str | None = None
    input: list[dict] | None = None
    final_message: str | None = None
    deferred_tools: DeferredTools | None = None
    created_at: datetime


class SessionDetailResponse(BaseModel):
    """Session index with optional hydrated SDK state."""

    index: SessionResponse
    display_messages: list[dict] | None = None
    state: dict | None = None


class SessionStatusResponse(BaseModel):
    """Current session execution status."""

    session_id: str
    status: SessionStatus
    transport: Transport | None = None
    stream_key: str | None = None


# ---------------------------------------------------------------------------
# Execution requests
# ---------------------------------------------------------------------------


class _ExecutionInputMixin(BaseModel):
    """Shared fields for endpoints that accept user input."""

    input: list[InputPart] | None = None
    user_interactions: list[UserInteraction] | None = None
    tool_results: list[ToolResult] | None = None


class ConversationRunRequest(_ExecutionInputMixin):
    """Request body for POST /api/conversations/run."""

    conversation_id: str | None = Field(
        default=None,
        description="Existing conversation to continue. Null = new conversation.",
    )
    preset_id: str | None = Field(
        default=None,
        description="Agent preset. Required for new conversations.",
    )
    workspace_id: str | None = None
    project_ids: list[str] | None = None
    metadata: dict | None = None
    config_override: dict | None = None
    transport: Transport = Transport.SSE


class ConversationForkRequest(_ExecutionInputMixin):
    """Request body for POST /api/conversations/{id}/fork."""

    preset_id: str
    from_session_id: str | None = Field(
        default=None,
        description="Fork point. Default: latest committed session.",
    )
    workspace_id: str | None = None
    project_ids: list[str] | None = None
    metadata: dict | None = None
    config_override: dict | None = None
    transport: Transport = Transport.SSE


class ConversationFireRequest(_ExecutionInputMixin):
    """Request body for POST /api/conversations/{id}/fire."""

    preset_id: str | None = Field(
        default=None,
        description="Agent preset. Default: conversation's default_preset_id.",
    )
    workspace_id: str | None = None
    project_ids: list[str] | None = None
    config_override: dict | None = None
    transport: Transport = Transport.STREAM


class SteerRequest(BaseModel):
    """Request body for steering an active session."""

    input: list[InputPart]


class SessionExecuteRequest(_ExecutionInputMixin):
    """Request body for POST /api/sessions/execute."""

    preset_id: str
    parent_session_id: str | None = None
    fork: bool = False
    workspace_id: str | None = None
    project_ids: list[str] | None = None
    config_override: dict | None = None
    transport: Transport = Transport.SSE


# ---------------------------------------------------------------------------
# Execution responses
# ---------------------------------------------------------------------------


class ActiveSessionInfo(BaseModel):
    """Info about a currently active session."""

    session_id: str
    stream_key: str | None = None
    transport: Transport


class ExecuteAcceptedResponse(BaseModel):
    """Response for transport=stream (202 Accepted)."""

    session_id: str
    conversation_id: str
    stream_key: str


class ConversationBusyResponse(BaseModel):
    """409 response when conversation already has an active agent session."""

    error: str = "conversation_busy"
    active_session: ActiveSessionInfo


class MailboxMessageResponse(BaseModel):
    """Serialized mailbox message returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    message_id: str
    conversation_id: str
    source_session_id: str
    source_type: MailboxSourceType
    subagent_name: str
    created_at: datetime
    delivered_to: str | None = None


# ---------------------------------------------------------------------------
# Toolsets (capability discovery)
# ---------------------------------------------------------------------------


class ToolsetInfo(BaseModel):
    """Describes a single available toolset and its constituent tools."""

    name: str
    """Canonical toolset name used in ToolsetSpec.toolset_name."""

    description: str
    """Human-readable description of what this toolset provides."""

    tools: list[str]
    """Names of individual tools included in this toolset."""

    is_alias: bool = False
    """True for 'core', which expands to all built-in toolsets."""


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Input for creating a new user."""

    user_id: str
    display_name: str
    role: UserRole = UserRole.USER


class UserUpdate(BaseModel):
    """Partial user update."""

    display_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    """Serialized user returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreateResponse(BaseModel):
    """Response for user creation -- includes the initial API key and password."""

    user: UserResponse
    password: str
    api_key: ApiKeyCreateResponse


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


class ApiKeyCreate(BaseModel):
    """Input for creating a new API key."""

    name: str
    user_id: str | None = Field(
        default=None,
        description="Target user (admin only, default: self).",
    )
    expires_in_days: int | None = Field(
        default=None,
        description="Days until expiration (default: never).",
    )


class ApiKeyCreateResponse(BaseModel):
    """Response for key creation -- includes the full key (shown once)."""

    key_id: str
    key: str
    name: str


class ApiKeyResponse(BaseModel):
    """Serialized API key metadata (never includes the full key)."""

    model_config = ConfigDict(from_attributes=True)

    key_id: str
    key_prefix: str
    user_id: str
    name: str
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Auth (login, password management)
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Input for password-based login."""

    user_id: str
    password: str


class LoginResponse(BaseModel):
    """Response for successful login -- includes JWT and user profile."""

    token: str
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    """Input for self-service password change."""

    old_password: str
    new_password: str = Field(min_length=8)


class ResetPasswordResponse(BaseModel):
    """Response for admin-initiated password reset."""

    password: str
