"""MCP runtime mapping.

Maps Netherbrain's ``McpConfig`` domain model to the underlying pydantic-ai
MCP client objects and the ya-agent-sdk ``ToolProxyToolset`` wrapper.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from netherbrain.agent_runtime.models.preset import McpServerSpec, McpTransport

if TYPE_CHECKING:
    from pydantic_ai.mcp import MCPServer
    from pydantic_ai.toolsets.abstract import AbstractToolset
    from ya_agent_sdk.context import AgentContext

logger = logging.getLogger(__name__)


class McpConfig(BaseModel):
    """Internal MCP runtime configuration.

    Keeps Netherbrain's MCP proxy policy inside the execution layer while the
    external preset/API boundary remains a simple ``mcp_servers`` list.
    """

    servers: list[McpServerSpec] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)
    optional_namespaces: list[str] = Field(default_factory=list)


def build_mcp_config(servers: list[McpServerSpec]) -> McpConfig:
    """Build internal MCP config from the external preset/API server list."""
    optional_namespaces = [spec.tool_prefix for spec in servers if spec.optional and spec.tool_prefix]
    return McpConfig(
        servers=servers,
        optional_namespaces=optional_namespaces,
    )


def build_mcp_servers(config: McpConfig) -> list[MCPServer]:
    """Build raw pydantic-ai MCP server instances from Netherbrain config."""
    if not config.servers:
        return []

    try:
        from pydantic_ai.mcp import MCPServerSSE, MCPServerStreamableHTTP
    except ImportError:
        logger.warning("pydantic-ai[mcp] not installed, skipping MCP server configuration")
        return []

    servers: list[MCPServer] = []
    for spec in config.servers:
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


def build_mcp_toolset(
    config: McpConfig,
) -> AbstractToolset[AgentContext] | None:
    """Build the ToolProxy MCP toolset from Netherbrain config."""
    servers = build_mcp_servers(config)
    if not servers:
        return None

    try:
        from ya_agent_sdk.toolsets.tool_proxy import ToolProxyToolset
    except ImportError:
        logger.warning("ya-agent-sdk tool_proxy not available, skipping MCP toolset configuration")
        return None

    descriptions = {
        spec.tool_prefix: spec.description for spec in config.servers if spec.tool_prefix and spec.description
    }

    toolset = ToolProxyToolset(
        toolsets=servers,
        namespace_descriptions=descriptions or None,
        max_results=config.max_results,
        optional_namespaces=set(config.optional_namespaces) or None,
    )

    logger.info(
        "Built MCP ToolProxyToolset: servers=%d, descriptions=%d, optional=%d, max_results=%d",
        len(config.servers),
        len(descriptions),
        len(config.optional_namespaces),
        config.max_results,
    )
    return toolset
