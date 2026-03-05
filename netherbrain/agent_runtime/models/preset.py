"""Agent preset data models.

These are pure Pydantic models representing the domain objects defined in
spec/agent_runtime/02-configuration.md.  They are used for API I/O, config
resolution, and later mapped to/from database rows.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator

from netherbrain.agent_runtime.models.enums import EnvironmentMode

# -- MCP server connections ---------------------------------------------------


class McpTransport(StrEnum):
    """Network transport for external MCP server connections."""

    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


class McpServerSpec(BaseModel):
    """External MCP server connection (non-stdio).

    Each entry creates a pydantic-ai MCP client toolset at runtime.
    Only network-based transports are supported.
    """

    url: str = Field(description="HTTP endpoint URL of the MCP server")
    transport: McpTransport = McpTransport.STREAMABLE_HTTP
    headers: dict[str, str] | None = Field(default=None, description="Custom HTTP headers (e.g., auth tokens)")
    tool_prefix: str | None = Field(default=None, description="Namespace prefix for tools")
    timeout: float | None = Field(default=None, description="Connection timeout in seconds")


# -- Preset components -------------------------------------------------------


class ModelPreset(BaseModel):
    """LLM model selection and settings.

    Uses SDK preset names for common provider configurations, with optional
    dict overrides for fine-tuning.  Resolution order:

    - ModelSettings: preset dict (from model_settings_preset) <- model_settings override
    - ModelConfig: preset dict (from model_config_preset) <- model_config override
    """

    name: str = Field(description="Provider-qualified model name, e.g. 'anthropic:claude-sonnet-4'")
    model_settings_preset: str | None = Field(
        default=None, description="SDK ModelSettings preset name, e.g. 'anthropic_high'"
    )
    model_settings: dict | None = Field(
        default=None, description="Explicit ModelSettings overrides (merged on top of preset)"
    )
    model_config_preset: str | None = Field(default=None, description="SDK ModelConfig preset name, e.g. 'claude_200k'")
    model_config_overrides: dict | None = Field(
        default=None,
        description="Explicit ModelConfig overrides (merged on top of preset). "
        "Named 'model_config_overrides' to avoid collision with Pydantic's reserved 'model_config' attribute.",
    )


class ToolsetSpec(BaseModel):
    """Declares which tool group is enabled and optional exclusions."""

    toolset_name: str
    enabled: bool = True
    exclude_tools: list[str] = Field(default_factory=list)


class ToolConfigSpec(BaseModel):
    """Non-secret tool configuration stored in the preset.

    API keys are auto-loaded from environment variables by the SDK.
    Media hooks are configured at the service level (NetherSettings).
    This spec covers only the per-preset knobs.
    """

    skip_url_verification: bool = True
    enable_load_document: bool = False
    image_understanding_model: str | None = None
    image_understanding_model_settings: dict | None = None
    video_understanding_model: str | None = None
    video_understanding_model_settings: dict | None = None


class EnvironmentSpec(BaseModel):
    """Environment mode and project configuration."""

    mode: EnvironmentMode = EnvironmentMode.LOCAL
    workspace_id: str | None = Field(
        default=None, description="Reference to a saved workspace (mutually exclusive with project_ids)"
    )
    project_ids: list[str] | None = Field(
        default=None, description="Inline project list for ad-hoc use (mutually exclusive with workspace_id)"
    )
    container_id: str | None = None
    container_workdir: str = "/workspace"

    @model_validator(mode="after")
    def _validate_sandbox_requires_container(self) -> Self:
        if self.mode == EnvironmentMode.SANDBOX and not self.container_id:
            msg = "container_id is required when mode is 'sandbox'"
            raise ValueError(msg)
        return self


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
    tool_config: ToolConfigSpec = Field(default_factory=ToolConfigSpec)
    subagents: SubagentSpec = Field(default_factory=SubagentSpec)
    mcp_servers: list[McpServerSpec] = Field(default_factory=list)
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
