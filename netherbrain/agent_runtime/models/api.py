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

from netherbrain.agent_runtime.models.enums import ConversationStatus
from netherbrain.agent_runtime.models.preset import (
    EnvironmentSpec,
    ModelPreset,
    SubagentSpec,
    ToolsetSpec,
)

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
    subagents: SubagentSpec = Field(default_factory=SubagentSpec)
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
    subagents: SubagentSpec | None = None
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
    subagents: SubagentSpec
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


class WorkspaceUpdate(BaseModel):
    """Partial workspace update."""

    name: str | None = None
    projects: list[str] | None = None


class WorkspaceResponse(BaseModel):
    """Serialized workspace returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    workspace_id: str
    name: str | None = None
    projects: list[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Conversation (read-only for now)
# ---------------------------------------------------------------------------


class ConversationResponse(BaseModel):
    """Serialized conversation returned to clients.

    The ORM attribute is ``metadata_`` (to avoid shadowing the Pydantic
    reserved name), so we use ``validation_alias`` to read it correctly.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    conversation_id: str
    title: str | None = None
    default_preset_id: str | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
