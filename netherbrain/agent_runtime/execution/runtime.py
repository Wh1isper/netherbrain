"""SDK adapter -- maps ResolvedConfig to ``create_agent()`` and ``stream_agent()``.

This module is the bridge between Netherbrain's configuration model and
the ya-agent-sdk.  It translates:

- ``ToolsetSpec`` -> SDK ``BaseTool`` classes
- ``ModelPreset`` -> SDK model string + ``ModelSettings``
- ``SubagentSpec`` -> SDK ``SubagentConfig`` list
- ``ResolvedConfig`` -> ``create_agent()`` call -> ``AgentRuntime``

The returned ``AgentRuntime`` is ready to be used with ``stream_agent()``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai import DeferredToolRequests, ModelSettings
from ya_agent_sdk.agents.main import AgentRuntime, create_agent
from ya_agent_sdk.context import AgentContext, ModelConfig, ResumableState, ToolConfig
from ya_agent_sdk.toolsets.core.base import BaseTool
from ya_agent_sdk.toolsets.core.content import tools as content_tools
from ya_agent_sdk.toolsets.core.context import tools as context_tools
from ya_agent_sdk.toolsets.core.document import tools as document_tools
from ya_agent_sdk.toolsets.core.enhance import tools as enhance_tools
from ya_agent_sdk.toolsets.core.filesystem import tools as filesystem_tools
from ya_agent_sdk.toolsets.core.multimodal import tools as multimodal_tools
from ya_agent_sdk.toolsets.core.shell import tools as shell_tools
from ya_agent_sdk.toolsets.core.subagent import tools as subagent_tools
from ya_agent_sdk.toolsets.core.web import tools as web_tools

from netherbrain.agent_runtime.execution.environment import (
    ProjectPaths,
    create_environment,
)
from netherbrain.agent_runtime.execution.prompt import render_system_prompt
from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
from netherbrain.agent_runtime.instrument import create_global_hooks, create_model_wrapper, create_subagent_wrapper
from netherbrain.agent_runtime.models.preset import (
    McpServerSpec,
    McpTransport,
    ModelPreset,
    SubagentSpec,
    ToolConfigSpec,
    ToolsetSpec,
)
from netherbrain.agent_runtime.settings import NetherSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.mcp import MCPServer
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.toolsets.abstract import AbstractToolset
    from y_agent_environment.resources import ResourceRegistryState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Toolset mapping
# ---------------------------------------------------------------------------

# Maps toolset_name (from preset config) to SDK BaseTool classes.
# Keys are the canonical names used in ToolsetSpec.toolset_name.
TOOLSET_REGISTRY: dict[str, list[type[BaseTool]]] = {
    "content": content_tools,
    "context": context_tools,
    "document": document_tools,
    "enhance": enhance_tools,
    "filesystem": filesystem_tools,
    "multimodal": multimodal_tools,
    "shell": shell_tools,
    "web": web_tools,
    # "subagent" is handled separately via SubagentSpec
}

# Convenience alias: "core" enables the standard set used by yaacli.
_CORE_TOOLSETS = [
    "content",
    "context",
    "document",
    "enhance",
    "filesystem",
    "multimodal",
    "shell",
    "web",
]


def resolve_tools(toolsets: list[ToolsetSpec]) -> list[type[BaseTool]]:
    """Map ``ToolsetSpec`` list to SDK ``BaseTool`` classes.

    Handles:
    - ``enabled=False`` -> skip the toolset entirely
    - ``exclude_tools`` -> filter out specific tool classes by name
    - ``toolset_name="core"`` -> expands to all standard toolsets

    Unknown toolset names are logged as warnings and skipped.
    """
    tools: list[type[BaseTool]] = []
    seen_names: set[str] = set()

    for spec in toolsets:
        if not spec.enabled:
            continue

        # Expand "core" alias to all standard toolsets.
        names = _CORE_TOOLSETS if spec.toolset_name == "core" else [spec.toolset_name]

        for name in names:
            if name in seen_names:
                continue
            seen_names.add(name)

            registry_tools = TOOLSET_REGISTRY.get(name)
            if registry_tools is None:
                logger.warning("Unknown toolset '%s', skipping", name)
                continue

            if spec.exclude_tools:
                exclude_set = set(spec.exclude_tools)
                filtered = [t for t in registry_tools if t.__name__ not in exclude_set]
                tools.extend(filtered)
            else:
                tools.extend(registry_tools)

    return tools


# ---------------------------------------------------------------------------
# Model mapping
# ---------------------------------------------------------------------------


def resolve_model_settings(model: ModelPreset) -> ModelSettings:
    """Map ``ModelPreset`` to SDK ``ModelSettings``.

    Resolution order:
    1. Load SDK preset dict (if ``model_settings_preset`` is set).
    2. Shallow-merge ``model_settings`` dict on top (override wins).
    3. Return as ``ModelSettings``.
    """
    from ya_agent_sdk.presets import get_model_settings as sdk_get_model_settings

    base: dict[str, Any] = {}
    if model.model_settings_preset is not None:
        base = dict(sdk_get_model_settings(model.model_settings_preset))
    if model.model_settings is not None:
        base = {**base, **model.model_settings}
    return ModelSettings(**base) if base else ModelSettings()


def resolve_model_config(model: ModelPreset) -> ModelConfig:
    """Map ``ModelPreset`` to SDK ``ModelConfig``.

    Resolution order:
    1. Load SDK preset dict (if ``model_config_preset`` is set).
    2. Shallow-merge ``model_config`` dict on top (override wins).
    3. Return as ``ModelConfig``.
    """
    from ya_agent_sdk.presets import get_model_cfg as sdk_get_model_cfg

    base: dict[str, Any] = {}
    if model.model_config_preset is not None:
        base = dict(sdk_get_model_cfg(model.model_config_preset))
    if model.model_config_overrides is not None:
        base = {**base, **model.model_config_overrides}
    return ModelConfig(**base) if base else ModelConfig()


# ---------------------------------------------------------------------------
# Tool config mapping
# ---------------------------------------------------------------------------


def resolve_tool_config(spec: ToolConfigSpec) -> ToolConfig:
    """Map ``ToolConfigSpec`` to SDK ``ToolConfig``.

    Non-secret settings come from the preset.  API keys are auto-loaded
    from environment variables by the SDK's ``ToolConfig`` defaults.
    """
    kwargs: dict[str, Any] = {
        "skip_url_verification": spec.skip_url_verification,
        "enable_load_document": spec.enable_load_document,
    }
    if spec.image_understanding_model is not None:
        kwargs["image_understanding_model"] = spec.image_understanding_model
    if spec.image_understanding_model_settings is not None:
        kwargs["image_understanding_model_settings"] = ModelSettings(**spec.image_understanding_model_settings)
    if spec.video_understanding_model is not None:
        kwargs["video_understanding_model"] = spec.video_understanding_model
    if spec.video_understanding_model_settings is not None:
        kwargs["video_understanding_model_settings"] = ModelSettings(**spec.video_understanding_model_settings)
    return ToolConfig(**kwargs)


# ---------------------------------------------------------------------------
# Subagent mapping
# ---------------------------------------------------------------------------


def resolve_subagent_configs(
    spec: SubagentSpec,
) -> list[Any]:
    """Map ``SubagentSpec`` to SDK ``SubagentConfig`` list.

    Synchronous (built-in) subagents are handled by the SDK's native
    subagent infrastructure.  Async subagents are handled separately
    via the ``async_delegate`` tool injected through ``extra_agent_tools``.

    Currently returns an empty list -- all subagent orchestration in
    Netherbrain uses the async delegate pattern.
    """
    return []


# ---------------------------------------------------------------------------
# MCP server mapping
# ---------------------------------------------------------------------------


def _build_mcp_server_instances(
    specs: list[McpServerSpec],
) -> list[MCPServer]:
    """Build raw pydantic-ai MCP server instances from specs.

    Each spec becomes an ``MCPServerStreamableHTTP`` or ``MCPServerSSE``
    instance.  Returns an empty list if no specs or if the ``mcp``
    optional dependency is not installed.
    """
    if not specs:
        return []

    try:
        from pydantic_ai.mcp import MCPServerSSE, MCPServerStreamableHTTP
    except ImportError:
        logger.warning("pydantic-ai[mcp] not installed, skipping MCP server configuration")
        return []

    servers: list[MCPServer] = []
    for spec in specs:
        kwargs: dict[str, Any] = {}
        if spec.headers:
            kwargs["headers"] = spec.headers
        if spec.tool_prefix:
            kwargs["tool_prefix"] = spec.tool_prefix
        if spec.timeout is not None:
            kwargs["timeout"] = spec.timeout

        if spec.transport == McpTransport.SSE:
            server = MCPServerSSE(spec.url, **kwargs)
        else:
            server = MCPServerStreamableHTTP(spec.url, **kwargs)

        servers.append(server)
        logger.info("MCP server configured: %s (%s)", spec.url, spec.transport)

    return servers


def resolve_mcp_servers(
    specs: list[McpServerSpec],
) -> AbstractToolset[AgentContext] | list[MCPServer] | None:
    """Wrap MCP servers in ``ToolSearchToolSet`` for on-demand tool loading.

    Each ``McpServerSpec`` becomes a pydantic-ai MCP server instance, then
    all servers are wrapped in a single ``ToolSearchToolSet``.  The model
    sees only a ``tool_search`` tool initially and discovers MCP tools
    on demand, reducing context usage.

    ``tool_prefix`` serves as the namespace ID; ``description`` provides
    the human-readable namespace description for search.

    Returns ``None`` if no MCP servers are configured or dependencies
    are missing.
    """
    servers = _build_mcp_server_instances(specs)
    if not servers:
        return None

    try:
        from ya_agent_sdk.toolsets.tool_search import ToolSearchToolSet, create_best_strategy
    except ImportError:
        logger.warning("ya-agent-sdk tool_search not available, passing MCP servers directly")
        # Graceful fallback: return raw servers as a list (old behavior).
        return servers

    # Extract namespace descriptions from specs.
    descriptions: dict[str, str] = {}
    for spec in specs:
        if spec.description and spec.tool_prefix:
            descriptions[spec.tool_prefix] = spec.description

    toolset = ToolSearchToolSet(
        toolsets=servers,
        namespace_descriptions=descriptions or None,
        search_strategy=create_best_strategy(),
    )

    logger.info(
        "Wrapped %d MCP servers in ToolSearchToolSet (descriptions: %d)",
        len(servers),
        len(descriptions),
    )
    return toolset


# ---------------------------------------------------------------------------
# Runtime factory
# ---------------------------------------------------------------------------


def create_service_runtime(
    config: ResolvedConfig,
    settings: NetherSettings,
    *,
    state: ResumableState | None = None,
    message_history: Sequence[ModelMessage] | None = None,
    resource_state: ResourceRegistryState | None = None,
    extra_agent_tools: Sequence[Any] | None = None,
) -> tuple[AgentRuntime[AgentContext, str | DeferredToolRequests, Any], ProjectPaths]:
    """Create an SDK ``AgentRuntime`` from a fully resolved config.

    This is the main entry point for the execution pipeline. It:

    1. Resolves project paths and ensures directories exist.
    2. Maps toolsets to SDK tool classes.
    3. Builds model settings and config.
    4. Calls ``create_agent()`` to produce an ``AgentRuntime``.

    The returned runtime is NOT entered -- the caller (coordinator) must
    use it as an async context manager or pass it to ``stream_agent()``.

    Parameters
    ----------
    config:
        Fully resolved execution config (from ``resolve_config``).
    settings:
        Service settings (data_root, data_prefix).
    state:
        Optional resumable state to restore (continue / fork).
    message_history:
        Optional conversation history for the agent.
    resource_state:
        Optional resource registry state to restore in the environment.
    extra_agent_tools:
        Optional pydantic-ai Tool instances to inject (e.g. async_delegate).

    Returns
    -------
    tuple of (AgentRuntime, ProjectPaths)
        The runtime for ``stream_agent()`` and paths for session commit.
    """
    # -- Environment -----------------------------------------------------------
    env, paths = create_environment(config, settings, resource_state=resource_state)

    # -- Tools -----------------------------------------------------------------
    tools = resolve_tools(config.toolsets)

    # Pure conversation mode: no projects -> strip filesystem and shell tools
    # so the agent cannot access the host filesystem or run commands.
    if not paths.has_projects:
        _fs_shell_tools = {*filesystem_tools, *shell_tools}
        tools = [t for t in tools if t not in _fs_shell_tools]

    # Always include subagent introspection tools.
    all_tools = [*tools, *subagent_tools]

    # -- System prompt ---------------------------------------------------------
    system_prompt = render_system_prompt(config)

    # -- Model -----------------------------------------------------------------
    model_settings = resolve_model_settings(config.model)
    model_cfg = resolve_model_config(config.model)

    # -- Subagents -------------------------------------------------------------
    subagent_configs = resolve_subagent_configs(config.subagents)

    # -- Tool config -----------------------------------------------------------
    tool_config = resolve_tool_config(config.tool_config)

    # -- MCP servers -----------------------------------------------------------
    # ToolSearchToolSet must be the LAST toolset so that dynamically loaded
    # tools are appended to the end of the model's tool list, keeping all
    # existing tool positions stable for KV cache reuse.  Within the toolset,
    # tool_search itself is always the first tool (handled by the SDK).
    mcp_toolset = resolve_mcp_servers(config.mcp_servers)
    toolsets: list[AbstractToolset[AgentContext]] | None = None
    if mcp_toolset is not None:
        # ToolSearchToolSet (single wrapper) or list[MCPServer] (fallback).
        toolsets = [mcp_toolset] if not isinstance(mcp_toolset, list) else mcp_toolset  # type: ignore[list-item]

    # -- Create runtime --------------------------------------------------------
    runtime = create_agent(
        model=config.model.name,
        model_settings=model_settings,
        model_cfg=model_cfg,
        output_type=[str, DeferredToolRequests],
        env=env,
        tools=all_tools,
        toolsets=toolsets,
        tool_config=tool_config,
        system_prompt=system_prompt,
        state=state,
        subagent_configs=subagent_configs if subagent_configs else None,
        unified_subagents=True,
        agent_name="netherbrain",
        model_wrapper=create_model_wrapper(),
        global_hooks=create_global_hooks(),
        subagent_wrapper=create_subagent_wrapper(),
        inherit_hooks=True,
        agent_tools=list(extra_agent_tools) if extra_agent_tools else None,
    )

    logger.info(
        "Created service runtime: model=%s, tools=%d, mcp_servers=%d, projects=%d",
        config.model.name,
        len(all_tools),
        len(config.mcp_servers),
        len(config.project_ids),
    )

    return runtime, paths
