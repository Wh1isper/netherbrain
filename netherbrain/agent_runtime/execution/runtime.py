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
)
from netherbrain.agent_runtime.execution.prompt import render_system_prompt
from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
from netherbrain.agent_runtime.models.preset import ModelPreset, SubagentSpec, ToolConfigSpec, ToolsetSpec
from netherbrain.agent_runtime.settings import NetherSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.messages import ModelMessage
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

    Only explicitly set fields are included; ``None`` values are omitted
    so the SDK uses its own defaults.
    """
    settings: dict[str, Any] = {}
    if model.temperature is not None:
        settings["temperature"] = model.temperature
    if model.max_tokens is not None:
        settings["max_tokens"] = model.max_tokens
    return ModelSettings(**settings) if settings else ModelSettings()


def resolve_model_config(model: ModelPreset) -> ModelConfig:
    """Map ``ModelPreset`` to SDK ``ModelConfig``."""
    kwargs: dict[str, Any] = {}
    if model.context_window is not None:
        kwargs["context_window"] = model.context_window
    return ModelConfig(**kwargs)


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

    Each ``SubagentRef`` in the spec becomes a SubagentConfig pointing
    to a Netherbrain preset.  The actual agent creation is deferred to
    the SDK's subagent infrastructure.

    TODO: Implement once async subagent execution (Phase 8) is ready.
    Currently returns an empty list.
    """
    # Phase 8: async_delegate + subagent refs -> SubagentConfig
    return []


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

    Returns
    -------
    tuple of (AgentRuntime, ProjectPaths)
        The runtime for ``stream_agent()`` and paths for session commit.
    """
    # -- Environment -----------------------------------------------------------
    from netherbrain.agent_runtime.execution.environment import create_environment

    env, paths = create_environment(config, settings, resource_state=resource_state)

    # -- Tools -----------------------------------------------------------------
    tools = resolve_tools(config.toolsets)

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

    # -- Create runtime --------------------------------------------------------
    runtime = create_agent(
        model=config.model.name,
        model_settings=model_settings,
        model_cfg=model_cfg,
        output_type=[str, DeferredToolRequests],
        env=env,
        tools=all_tools,
        tool_config=tool_config,
        system_prompt=system_prompt,
        state=state,
        subagent_configs=subagent_configs if subagent_configs else None,
        unified_subagents=True,
        agent_name="netherbrain",
    )

    logger.info(
        "Created service runtime: model=%s, tools=%d, projects=%d",
        config.model.name,
        len(all_tools),
        len(config.project_ids),
    )

    return runtime, paths
