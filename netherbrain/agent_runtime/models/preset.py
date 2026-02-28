"""Agent preset data models.

These are pure Pydantic models representing the domain objects defined in
spec/agent_runtime/02-configuration.md.  They are used for API I/O, config
resolution, and later mapped to/from database rows.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from netherbrain.agent_runtime.models.enums import ShellMode

# -- Preset components -------------------------------------------------------


class ModelPreset(BaseModel):
    """LLM model selection and settings."""

    name: str = Field(description="Provider-qualified model name, e.g. 'anthropic:claude-sonnet-4'")
    context_window: int | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class ToolsetSpec(BaseModel):
    """Declares which tool group is enabled and optional exclusions."""

    toolset_name: str
    enabled: bool = True
    exclude_tools: list[str] = Field(default_factory=list)


class EnvironmentSpec(BaseModel):
    """Shell execution mode and filesystem paths."""

    shell_mode: ShellMode = ShellMode.LOCAL
    container_id: str | None = None
    container_workdir: str | None = None
    default_path: str = "."
    allowed_paths: list[str] = Field(default_factory=list)


class SubagentRef(BaseModel):
    """Reference to another preset used as a subagent."""

    preset_id: str
    name: str
    description: str
    instruction: str | None = None


class SubagentSpec(BaseModel):
    """Subagent configuration block within a preset."""

    include_builtin: bool = True
    async_enabled: bool = False
    refs: list[SubagentRef] = Field(default_factory=list)


# -- Top-level preset --------------------------------------------------------


class AgentPreset(BaseModel):
    """Full agent preset as stored in PostgreSQL."""

    preset_id: str
    name: str
    description: str | None = None
    model: ModelPreset
    system_prompt: str
    toolsets: list[ToolsetSpec] = Field(default_factory=list)
    environment: EnvironmentSpec = Field(default_factory=EnvironmentSpec)
    subagents: SubagentSpec = Field(default_factory=SubagentSpec)
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
