"""Unit tests for SDK adapter (toolset/model mapping, runtime factory)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# MCP server types
# ---------------------------------------------------------------------------
from netherbrain.agent_runtime.execution.mcp import McpConfig
from netherbrain.agent_runtime.execution.runtime import (
    TOOLSET_REGISTRY,
    resolve_model_config,
    resolve_model_settings,
    resolve_tools,
)
from netherbrain.agent_runtime.models.preset import McpServerSpec, McpTransport, ModelPreset, SubagentSpec, ToolsetSpec

# ---------------------------------------------------------------------------
# resolve_tools
# ---------------------------------------------------------------------------


def test_resolve_tools_single_toolset() -> None:
    specs = [ToolsetSpec(toolset_name="shell")]
    tools = resolve_tools(specs)

    assert len(tools) > 0
    for t in tools:
        assert isinstance(t, type)


def test_resolve_tools_multiple_toolsets() -> None:
    specs = [
        ToolsetSpec(toolset_name="shell"),
        ToolsetSpec(toolset_name="filesystem"),
    ]
    tools = resolve_tools(specs)

    shell_count = len(TOOLSET_REGISTRY["shell"])
    fs_count = len(TOOLSET_REGISTRY["filesystem"])
    assert len(tools) == shell_count + fs_count


def test_resolve_tools_disabled_skipped() -> None:
    specs = [
        ToolsetSpec(toolset_name="shell", enabled=False),
        ToolsetSpec(toolset_name="web"),
    ]
    tools = resolve_tools(specs)

    shell_classes = {t.__name__ for t in TOOLSET_REGISTRY["shell"]}
    returned_names = {t.__name__ for t in tools}
    assert shell_classes.isdisjoint(returned_names)


def test_resolve_tools_exclude() -> None:
    shell_tool_name = TOOLSET_REGISTRY["shell"][0].__name__

    specs = [ToolsetSpec(toolset_name="shell", exclude_tools=[shell_tool_name])]
    tools = resolve_tools(specs)

    returned_names = {t.__name__ for t in tools}
    assert shell_tool_name not in returned_names


def test_resolve_tools_core_alias() -> None:
    specs = [ToolsetSpec(toolset_name="core")]
    tools = resolve_tools(specs)

    expected_count = sum(
        len(TOOLSET_REGISTRY[name])
        for name in [
            "content",
            "context",
            "document",
            "enhance",
            "filesystem",
            "multimodal",
            "shell",
            "web",
        ]
    )
    assert len(tools) == expected_count


def test_resolve_tools_core_deduplicates() -> None:
    specs = [
        ToolsetSpec(toolset_name="core"),
        ToolsetSpec(toolset_name="shell"),
    ]
    tools = resolve_tools(specs)

    core_only = resolve_tools([ToolsetSpec(toolset_name="core")])
    assert len(tools) == len(core_only)


def test_resolve_tools_unknown_skipped() -> None:
    specs = [ToolsetSpec(toolset_name="nonexistent")]
    assert resolve_tools(specs) == []


def test_resolve_tools_empty() -> None:
    assert resolve_tools([]) == []


def test_resolve_tools_all_registry_keys() -> None:
    for name in TOOLSET_REGISTRY:
        specs = [ToolsetSpec(toolset_name=name)]
        tools = resolve_tools(specs)
        assert isinstance(tools, list)


# ---------------------------------------------------------------------------
# resolve_model_settings
# ---------------------------------------------------------------------------


def test_resolve_model_settings_defaults() -> None:
    model = ModelPreset(name="anthropic:claude-sonnet-4")
    settings = resolve_model_settings(model)
    assert settings is not None


def test_resolve_model_settings_preset_only() -> None:
    model = ModelPreset(name="anthropic:claude-sonnet-4", model_settings_preset="anthropic_high")
    settings = resolve_model_settings(model)

    assert settings.get("anthropic_thinking") is not None
    assert settings.get("max_tokens") == 32768


def test_resolve_model_settings_override_only() -> None:
    model = ModelPreset(name="openai:gpt-4o", model_settings={"temperature": 0.7, "max_tokens": 4096})
    settings = resolve_model_settings(model)

    assert settings.get("temperature") == 0.7
    assert settings.get("max_tokens") == 4096


def test_resolve_model_settings_preset_plus_override() -> None:
    model = ModelPreset(
        name="anthropic:claude-sonnet-4",
        model_settings_preset="anthropic_medium",
        model_settings={"temperature": 0.3},
    )
    settings = resolve_model_settings(model)

    # Override applied
    assert settings.get("temperature") == 0.3
    # Preset base preserved
    assert settings.get("anthropic_thinking") is not None


# ---------------------------------------------------------------------------
# resolve_model_config
# ---------------------------------------------------------------------------


def test_resolve_model_config_defaults() -> None:
    model = ModelPreset(name="openai:gpt-4o")
    cfg = resolve_model_config(model)
    assert cfg is not None


def test_resolve_model_config_context_window() -> None:
    model = ModelPreset(name="anthropic:claude-sonnet-4", model_config_preset="claude_200k")
    cfg = resolve_model_config(model)
    assert cfg.context_window == 200_000


def test_resolve_model_config_override() -> None:
    model = ModelPreset(
        name="anthropic:claude-sonnet-4",
        model_config_preset="claude_200k",
        model_config_overrides={"context_window": 100_000},
    )
    cfg = resolve_model_config(model)
    assert cfg.context_window == 100_000


# ---------------------------------------------------------------------------
# create_service_runtime
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Build a minimal ResolvedConfig."""
    from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
    from netherbrain.agent_runtime.models.enums import EnvironmentMode

    defaults = {
        "preset_id": "test-preset",
        "model": ModelPreset(name="openai:gpt-4o"),
        "system_prompt": "You are a helpful assistant.",
        "toolsets": [ToolsetSpec(toolset_name="shell")],
        "subagents": SubagentSpec(),
        "mcp": McpConfig(),
        "environment_mode": EnvironmentMode.LOCAL,
        "project_ids": ["test-project"],
        "container_id": None,
        "container_workdir": None,
    }
    defaults.update(overrides)
    return ResolvedConfig(**defaults)


def _make_settings(tmp_path: Path):
    """Build a minimal NetherSettings-like mock."""
    settings = MagicMock()
    settings.data_root = str(tmp_path)
    settings.data_prefix = None
    return settings


@patch("netherbrain.agent_runtime.execution.runtime.create_agent")
def test_create_service_runtime(mock_create_agent: MagicMock, tmp_path: Path) -> None:
    from netherbrain.agent_runtime.execution.runtime import create_service_runtime

    mock_runtime = MagicMock()
    mock_create_agent.return_value = mock_runtime

    config = _make_config()
    settings = _make_settings(tmp_path)

    runtime, paths = create_service_runtime(config, settings)

    assert runtime is mock_runtime
    assert paths.default_project_id == "test-project"
    assert paths.default_real_path == tmp_path / "projects" / "test-project"

    mock_create_agent.assert_called_once()
    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["model"] == "openai:gpt-4o"
    assert call_kwargs["system_prompt"] == "You are a helpful assistant."
    assert call_kwargs["agent_name"] == "netherbrain"
    assert call_kwargs["unified_subagents"] is True


@patch("netherbrain.agent_runtime.execution.runtime.create_agent")
def test_create_service_runtime_directories(mock_create_agent: MagicMock, tmp_path: Path) -> None:
    from netherbrain.agent_runtime.execution.runtime import create_service_runtime

    mock_create_agent.return_value = MagicMock()
    config = _make_config(project_ids=["alpha", "beta"])
    settings = _make_settings(tmp_path)

    create_service_runtime(config, settings)

    assert (tmp_path / "projects" / "alpha").is_dir()
    assert (tmp_path / "projects" / "beta").is_dir()


@patch("netherbrain.agent_runtime.execution.runtime.create_agent")
def test_create_service_runtime_no_projects(mock_create_agent: MagicMock, tmp_path: Path) -> None:
    from netherbrain.agent_runtime.execution.runtime import create_service_runtime

    mock_create_agent.return_value = MagicMock()
    config = _make_config(project_ids=[])
    settings = _make_settings(tmp_path)

    _, paths = create_service_runtime(config, settings)

    assert not paths.has_projects


@patch("netherbrain.agent_runtime.execution.runtime.create_agent")
def test_create_service_runtime_state_passthrough(mock_create_agent: MagicMock, tmp_path: Path) -> None:
    from ya_agent_sdk.context import ResumableState

    from netherbrain.agent_runtime.execution.runtime import create_service_runtime

    mock_create_agent.return_value = MagicMock()
    config = _make_config()
    settings = _make_settings(tmp_path)
    state = ResumableState()

    create_service_runtime(config, settings, state=state)

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["state"] is state


@patch("netherbrain.agent_runtime.execution.runtime.create_agent")
def test_create_service_runtime_tools_mapped(mock_create_agent: MagicMock, tmp_path: Path) -> None:
    from netherbrain.agent_runtime.execution.runtime import create_service_runtime

    mock_create_agent.return_value = MagicMock()
    config = _make_config(
        toolsets=[
            ToolsetSpec(toolset_name="shell"),
            ToolsetSpec(toolset_name="web"),
        ],
    )
    settings = _make_settings(tmp_path)

    create_service_runtime(config, settings)

    call_kwargs = mock_create_agent.call_args[1]
    tool_classes = call_kwargs["tools"]
    # Should include shell + web + subagent introspection tools.
    assert len(tool_classes) > 0


# ---------------------------------------------------------------------------
# MCP runtime mapping
# ---------------------------------------------------------------------------


def test_build_mcp_servers_empty() -> None:
    from netherbrain.agent_runtime.execution.mcp import build_mcp_servers

    assert build_mcp_servers(McpConfig()) == []


def test_build_mcp_servers_streamable_http() -> None:
    from pydantic_ai.mcp import MCPServerStreamableHTTP

    from netherbrain.agent_runtime.execution.mcp import build_mcp_servers

    config = McpConfig(servers=[McpServerSpec(url="http://localhost:8080/mcp")])
    servers = build_mcp_servers(config)

    assert len(servers) == 1
    assert isinstance(servers[0], MCPServerStreamableHTTP)
    assert servers[0].url == "http://localhost:8080/mcp"


def test_build_mcp_servers_sse() -> None:
    from pydantic_ai.mcp import MCPServerSSE

    from netherbrain.agent_runtime.execution.mcp import build_mcp_servers

    config = McpConfig(servers=[McpServerSpec(url="http://localhost:3001/sse", transport=McpTransport.SSE)])
    servers = build_mcp_servers(config)

    assert len(servers) == 1
    assert isinstance(servers[0], MCPServerSSE)
    assert servers[0].url == "http://localhost:3001/sse"


def test_build_mcp_servers_with_headers_and_prefix() -> None:
    from pydantic_ai.mcp import MCPServerStreamableHTTP

    from netherbrain.agent_runtime.execution.mcp import build_mcp_servers

    config = McpConfig(
        servers=[
            McpServerSpec(
                url="http://mcp.example.com/api",
                headers={"Authorization": "Bearer secret"},
                tool_prefix="ext",
                timeout=30.0,
            )
        ]
    )
    servers = build_mcp_servers(config)

    assert len(servers) == 1
    server = servers[0]
    assert isinstance(server, MCPServerStreamableHTTP)
    assert server.url == "http://mcp.example.com/api"
    assert server.headers == {"Authorization": "Bearer secret"}
    assert server.tool_prefix == "ext"
    assert server.timeout == 30.0


def test_build_mcp_servers_multiple() -> None:
    from netherbrain.agent_runtime.execution.mcp import build_mcp_servers

    config = McpConfig(
        servers=[
            McpServerSpec(url="http://server1/mcp"),
            McpServerSpec(url="http://server2/sse", transport=McpTransport.SSE),
        ]
    )
    servers = build_mcp_servers(config)
    assert len(servers) == 2


def test_build_mcp_toolset_empty() -> None:
    from netherbrain.agent_runtime.execution.mcp import build_mcp_toolset

    assert build_mcp_toolset(McpConfig()) is None


def test_build_mcp_toolset_returns_tool_proxy_toolset() -> None:
    from ya_agent_sdk.toolsets.tool_proxy import ToolProxyToolset

    from netherbrain.agent_runtime.execution.mcp import build_mcp_toolset

    config = McpConfig(servers=[McpServerSpec(url="http://localhost:8080/mcp", tool_prefix="myserver")])
    result = build_mcp_toolset(config)

    assert isinstance(result, ToolProxyToolset)


def test_build_mcp_toolset_extracts_descriptions() -> None:
    from ya_agent_sdk.toolsets.tool_proxy import ToolProxyToolset

    from netherbrain.agent_runtime.execution.mcp import build_mcp_toolset

    config = McpConfig(
        servers=[
            McpServerSpec(
                url="http://localhost:8080/mcp",
                tool_prefix="files",
                description="File system operations",
            ),
            McpServerSpec(
                url="http://localhost:3001/sse",
                transport=McpTransport.SSE,
                tool_prefix="db",
                description="Database queries",
            ),
        ]
    )
    result = build_mcp_toolset(config)

    assert isinstance(result, ToolProxyToolset)
    assert result._namespace_descriptions == {
        "files": "File system operations",
        "db": "Database queries",
    }


def test_build_mcp_toolset_skips_description_without_prefix() -> None:
    from ya_agent_sdk.toolsets.tool_proxy import ToolProxyToolset

    from netherbrain.agent_runtime.execution.mcp import build_mcp_toolset

    config = McpConfig(
        servers=[
            McpServerSpec(
                url="http://localhost:8080/mcp",
                description="No prefix, should be skipped",
            ),
        ]
    )
    result = build_mcp_toolset(config)

    assert isinstance(result, ToolProxyToolset)
    assert result._namespace_descriptions == {}


def test_build_mcp_toolset_passes_proxy_settings() -> None:
    from ya_agent_sdk.toolsets.tool_proxy import ToolProxyToolset

    from netherbrain.agent_runtime.execution.mcp import build_mcp_toolset

    config = McpConfig(
        servers=[McpServerSpec(url="http://localhost:8080/mcp", tool_prefix="files")],
        max_results=9,
        optional_namespaces=["files"],
    )
    result = build_mcp_toolset(config)

    assert isinstance(result, ToolProxyToolset)
    assert result._max_results == 9
    assert result._optional_namespaces == {"files"}


def test_build_mcp_config_collects_optional_namespaces() -> None:
    from netherbrain.agent_runtime.execution.mcp import build_mcp_config

    config = build_mcp_config([
        McpServerSpec(url="http://required.example/mcp", tool_prefix="required"),
        McpServerSpec(url="http://optional.example/mcp", tool_prefix="optional", optional=True),
        McpServerSpec(url="http://no-prefix.example/mcp", optional=True),
    ])

    assert [server.url for server in config.servers] == [
        "http://required.example/mcp",
        "http://optional.example/mcp",
        "http://no-prefix.example/mcp",
    ]
    assert config.optional_namespaces == ["optional"]


@patch("netherbrain.agent_runtime.execution.runtime.create_agent")
def test_create_service_runtime_with_mcp_servers(mock_create_agent: MagicMock, tmp_path: Path) -> None:
    from ya_agent_sdk.toolsets.tool_proxy import ToolProxyToolset

    from netherbrain.agent_runtime.execution.runtime import create_service_runtime

    mock_runtime = MagicMock()
    mock_create_agent.return_value = mock_runtime

    config = _make_config(
        mcp=McpConfig(
            servers=[
                McpServerSpec(url="http://localhost:8080/mcp", tool_prefix="srv1"),
                McpServerSpec(
                    url="http://localhost:3001/sse",
                    transport=McpTransport.SSE,
                    tool_prefix="srv2",
                ),
            ]
        ),
    )
    settings = _make_settings(tmp_path)

    create_service_runtime(config, settings)

    call_kwargs = mock_create_agent.call_args[1]
    # Should pass a single-element list containing the ToolProxyToolset.
    assert call_kwargs["toolsets"] is not None
    assert len(call_kwargs["toolsets"]) == 1
    assert isinstance(call_kwargs["toolsets"][0], ToolProxyToolset)


@patch("netherbrain.agent_runtime.execution.runtime.create_agent")
def test_create_service_runtime_no_mcp_passes_none(mock_create_agent: MagicMock, tmp_path: Path) -> None:
    from netherbrain.agent_runtime.execution.runtime import create_service_runtime

    mock_runtime = MagicMock()
    mock_create_agent.return_value = mock_runtime

    config = _make_config()
    settings = _make_settings(tmp_path)

    create_service_runtime(config, settings)

    call_kwargs = mock_create_agent.call_args[1]
    # No MCP servers -> toolsets should be None.
    assert call_kwargs["toolsets"] is None
