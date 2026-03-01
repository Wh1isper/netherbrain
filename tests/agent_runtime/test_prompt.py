"""Unit tests for system prompt rendering."""

from __future__ import annotations

from netherbrain.agent_runtime.execution.prompt import render_system_prompt
from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
from netherbrain.agent_runtime.models.enums import ShellMode
from netherbrain.agent_runtime.models.preset import ModelPreset, SubagentSpec


def _make_config(**overrides) -> ResolvedConfig:
    defaults = {
        "preset_id": "test-preset",
        "model": ModelPreset(name="openai:gpt-4o"),
        "system_prompt": "You are a helpful assistant.",
        "toolsets": [],
        "subagents": SubagentSpec(),
        "shell_mode": ShellMode.LOCAL,
        "project_ids": ["my-project"],
    }
    defaults.update(overrides)
    return ResolvedConfig(**defaults)


def test_plain_string_passthrough() -> None:
    config = _make_config(system_prompt="You are a helpful assistant.")
    result = render_system_prompt(config)
    assert result == "You are a helpful assistant."


def test_template_with_project() -> None:
    config = _make_config(
        system_prompt="Working on {{ default_project }}.",
        project_ids=["my-app"],
    )
    result = render_system_prompt(config)
    assert result == "Working on my-app."


def test_template_with_multiple_projects() -> None:
    config = _make_config(
        system_prompt="Projects: {{ project_ids | join(', ') }}",
        project_ids=["alpha", "beta", "gamma"],
    )
    result = render_system_prompt(config)
    assert result == "Projects: alpha, beta, gamma"


def test_template_conditional() -> None:
    template = "You are an assistant.{% if project_ids | length > 1 %} Multi-project mode.{% endif %}"
    single = _make_config(system_prompt=template, project_ids=["one"])
    assert "Multi-project" not in render_system_prompt(single)

    multi = _make_config(system_prompt=template, project_ids=["one", "two"])
    assert "Multi-project" in render_system_prompt(multi)


def test_template_no_projects() -> None:
    config = _make_config(
        system_prompt="Project: {{ default_project }}",
        project_ids=[],
    )
    result = render_system_prompt(config)
    assert result == "Project: None"


def test_template_shell_mode() -> None:
    config = _make_config(
        system_prompt="Mode: {{ shell_mode }}",
        shell_mode=ShellMode.DOCKER,
    )
    result = render_system_prompt(config)
    assert result == "Mode: docker"


def test_template_model_name() -> None:
    config = _make_config(
        system_prompt="Using {{ model_name }}",
        model=ModelPreset(name="anthropic:claude-sonnet-4"),
    )
    result = render_system_prompt(config)
    assert result == "Using anthropic:claude-sonnet-4"


def test_template_preset_id() -> None:
    config = _make_config(
        system_prompt="Preset: {{ preset_id }}",
        preset_id="coding-agent",
    )
    result = render_system_prompt(config)
    assert result == "Preset: coding-agent"


def test_template_date() -> None:
    config = _make_config(system_prompt="Date: {{ date }}")
    result = render_system_prompt(config)
    # Should be a date string in YYYY-MM-DD format
    assert len(result.split(": ")[1]) == 10


def test_extra_vars() -> None:
    config = _make_config(
        system_prompt="User: {{ username }}",
    )
    result = render_system_prompt(config, extra_vars={"username": "alice"})
    assert result == "User: alice"


def test_extra_vars_override_default() -> None:
    config = _make_config(
        system_prompt="Project: {{ default_project }}",
        project_ids=["original"],
    )
    result = render_system_prompt(config, extra_vars={"default_project": "overridden"})
    assert result == "Project: overridden"


def test_no_jinja_syntax_fast_path() -> None:
    # Ensure strings without {{ or {% are returned as-is (no Jinja processing)
    config = _make_config(system_prompt="Plain prompt with { braces } but not Jinja.")
    result = render_system_prompt(config)
    assert result == "Plain prompt with { braces } but not Jinja."
