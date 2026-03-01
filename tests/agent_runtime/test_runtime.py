"""Unit tests for SDK adapter (toolset/model mapping, runtime factory)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from netherbrain.agent_runtime.execution.runtime import (
    TOOLSET_REGISTRY,
    resolve_model_config,
    resolve_model_settings,
    resolve_tools,
)
from netherbrain.agent_runtime.models.preset import ModelPreset, SubagentSpec, ToolsetSpec

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


def test_resolve_model_settings_all_fields() -> None:
    model = ModelPreset(name="openai:gpt-4o", temperature=0.7, max_tokens=4096)
    settings = resolve_model_settings(model)

    assert settings.get("temperature") == 0.7
    assert settings.get("max_tokens") == 4096


def test_resolve_model_settings_partial() -> None:
    model = ModelPreset(name="openai:gpt-4o", temperature=0.5)
    settings = resolve_model_settings(model)

    assert settings.get("temperature") == 0.5
    assert settings.get("max_tokens") is None


# ---------------------------------------------------------------------------
# resolve_model_config
# ---------------------------------------------------------------------------


def test_resolve_model_config_defaults() -> None:
    model = ModelPreset(name="openai:gpt-4o")
    cfg = resolve_model_config(model)
    assert cfg is not None


def test_resolve_model_config_context_window() -> None:
    model = ModelPreset(name="anthropic:claude-sonnet-4", context_window=200000)
    cfg = resolve_model_config(model)
    assert cfg.context_window == 200000


# ---------------------------------------------------------------------------
# create_service_runtime
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Build a minimal ResolvedConfig."""
    from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
    from netherbrain.agent_runtime.models.enums import ShellMode

    defaults = {
        "preset_id": "test-preset",
        "model": ModelPreset(name="openai:gpt-4o"),
        "system_prompt": "You are a helpful assistant.",
        "toolsets": [ToolsetSpec(toolset_name="shell")],
        "subagents": SubagentSpec(),
        "shell_mode": ShellMode.LOCAL,
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
