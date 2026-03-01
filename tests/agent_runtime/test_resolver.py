"""Integration tests for the config resolver."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Preset, Workspace
from netherbrain.agent_runtime.execution.resolver import (
    ConfigOverride,
    NoPresetError,
    ProjectConflictError,
    ResolvedConfig,
    WorkspaceNotFoundError,
    resolve_config,
)
from netherbrain.agent_runtime.models.enums import ShellMode
from netherbrain.agent_runtime.models.preset import (
    EnvironmentSpec,
    ModelPreset,
    SubagentSpec,
    ToolsetSpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_MODEL = {"name": "anthropic:claude-sonnet-4"}


async def _create_preset(
    db: AsyncSession,
    preset_id: str = "test-preset",
    *,
    is_default: bool = False,
    environment: dict | None = None,
    **kwargs: object,
) -> Preset:
    """Insert a preset row for testing."""
    row = Preset(
        preset_id=preset_id,
        name=kwargs.get("name", "Test"),
        model=kwargs.get("model", MINIMAL_MODEL),
        system_prompt=kwargs.get("system_prompt", "You are a test agent."),
        toolsets=kwargs.get("toolsets", []),
        environment=environment or {},
        subagents=kwargs.get("subagents", {}),
        is_default=is_default,
    )
    db.add(row)
    await db.flush()
    return row


async def _create_workspace(
    db: AsyncSession,
    workspace_id: str = "ws-1",
    projects: list[str] | None = None,
) -> Workspace:
    """Insert a workspace row for testing."""
    row = Workspace(
        workspace_id=workspace_id,
        projects=projects or ["proj-a", "proj-b"],
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Preset loading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_resolve_explicit_preset(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "my-preset", system_prompt="Hello {{name}}")

    cfg = await resolve_config(db_session, preset_id="my-preset")

    assert isinstance(cfg, ResolvedConfig)
    assert cfg.preset_id == "my-preset"
    assert cfg.model.name == "anthropic:claude-sonnet-4"
    assert cfg.system_prompt == "Hello {{name}}"


@pytest.mark.integration
async def test_resolve_default_preset(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "not-default")
    await _create_preset(db_session, "the-default", is_default=True, system_prompt="I am default")

    cfg = await resolve_config(db_session)

    assert cfg.preset_id == "the-default"
    assert cfg.system_prompt == "I am default"


@pytest.mark.integration
async def test_resolve_no_preset_raises(db_session: AsyncSession) -> None:
    with pytest.raises(NoPresetError, match="no default preset"):
        await resolve_config(db_session)


@pytest.mark.integration
async def test_resolve_preset_not_found_raises(db_session: AsyncSession) -> None:
    with pytest.raises(NoPresetError, match="ghost"):
        await resolve_config(db_session, preset_id="ghost")


# ---------------------------------------------------------------------------
# Override merging
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_override_model(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    override = ConfigOverride(model=ModelPreset(name="openai:gpt-4o", temperature=0.5))
    cfg = await resolve_config(db_session, override=override)

    assert cfg.model.name == "openai:gpt-4o"
    assert cfg.model.temperature == 0.5


@pytest.mark.integration
async def test_override_system_prompt(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True, system_prompt="original")

    override = ConfigOverride(system_prompt="overridden")
    cfg = await resolve_config(db_session, override=override)

    assert cfg.system_prompt == "overridden"


@pytest.mark.integration
async def test_override_toolsets(db_session: AsyncSession) -> None:
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        toolsets=[{"toolset_name": "core", "enabled": True}],
    )

    new_toolsets = [
        ToolsetSpec(toolset_name="core", enabled=True, exclude_tools=["shell"]),
        ToolsetSpec(toolset_name="web", enabled=True),
    ]
    override = ConfigOverride(toolsets=new_toolsets)
    cfg = await resolve_config(db_session, override=override)

    assert len(cfg.toolsets) == 2
    assert cfg.toolsets[0].exclude_tools == ["shell"]


@pytest.mark.integration
async def test_override_subagents(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    override = ConfigOverride(subagents=SubagentSpec(include_builtin=False, async_enabled=True))
    cfg = await resolve_config(db_session, override=override)

    assert cfg.subagents.include_builtin is False
    assert cfg.subagents.async_enabled is True


@pytest.mark.integration
async def test_override_shell_mode(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    override = ConfigOverride(
        environment=EnvironmentSpec(
            shell_mode=ShellMode.DOCKER,
            container_id="abc123",
            container_workdir="/app",
        )
    )
    cfg = await resolve_config(db_session, override=override)

    assert cfg.shell_mode == ShellMode.DOCKER
    assert cfg.container_id == "abc123"
    assert cfg.container_workdir == "/app"


@pytest.mark.integration
async def test_no_override_preserves_preset(db_session: AsyncSession) -> None:
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        model={"name": "openai:gpt-4o", "temperature": 0.7},
        system_prompt="Keep it short.",
        toolsets=[{"toolset_name": "core", "enabled": True}],
        environment={
            "shell_mode": "docker",
            "container_id": "ctr-1",
        },
        subagents={"include_builtin": False},
    )

    cfg = await resolve_config(db_session)

    assert cfg.model.name == "openai:gpt-4o"
    assert cfg.model.temperature == 0.7
    assert cfg.system_prompt == "Keep it short."
    assert len(cfg.toolsets) == 1
    assert cfg.shell_mode == ShellMode.DOCKER
    assert cfg.container_id == "ctr-1"
    assert cfg.subagents.include_builtin is False


# ---------------------------------------------------------------------------
# Project resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_request_project_ids(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    cfg = await resolve_config(db_session, project_ids=["my-proj"])

    assert cfg.project_ids == ["my-proj"]


@pytest.mark.integration
async def test_request_workspace_id(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)
    await _create_workspace(db_session, "ws-1", projects=["proj-x", "proj-y"])

    cfg = await resolve_config(db_session, workspace_id="ws-1")

    assert cfg.project_ids == ["proj-x", "proj-y"]


@pytest.mark.integration
async def test_request_workspace_and_projects_conflict(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    with pytest.raises(ProjectConflictError, match="mutually exclusive"):
        await resolve_config(db_session, workspace_id="ws", project_ids=["p"])


@pytest.mark.integration
async def test_request_workspace_not_found(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    with pytest.raises(WorkspaceNotFoundError, match="ghost-ws"):
        await resolve_config(db_session, workspace_id="ghost-ws")


@pytest.mark.integration
async def test_override_env_workspace(db_session: AsyncSession) -> None:
    """Override environment workspace_id takes priority over preset env."""
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        environment={"project_ids": ["preset-proj"]},
    )
    await _create_workspace(db_session, "override-ws", projects=["ov-proj"])

    override = ConfigOverride(environment=EnvironmentSpec(workspace_id="override-ws"))
    cfg = await resolve_config(db_session, override=override)

    assert cfg.project_ids == ["ov-proj"]


@pytest.mark.integration
async def test_override_env_project_ids(db_session: AsyncSession) -> None:
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        environment={"project_ids": ["preset-proj"]},
    )

    override = ConfigOverride(environment=EnvironmentSpec(project_ids=["inline-proj"]))
    cfg = await resolve_config(db_session, override=override)

    assert cfg.project_ids == ["inline-proj"]


@pytest.mark.integration
async def test_override_env_conflict_raises(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    override = ConfigOverride(environment=EnvironmentSpec(workspace_id="ws", project_ids=["p"]))
    with pytest.raises(ProjectConflictError, match="override"):
        await resolve_config(db_session, override=override)


@pytest.mark.integration
async def test_preset_env_workspace(db_session: AsyncSession) -> None:
    await _create_workspace(db_session, "preset-ws", projects=["a", "b"])
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        environment={"workspace_id": "preset-ws"},
    )

    cfg = await resolve_config(db_session)

    assert cfg.project_ids == ["a", "b"]


@pytest.mark.integration
async def test_preset_env_project_ids(db_session: AsyncSession) -> None:
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        environment={"project_ids": ["proj-1", "proj-2"]},
    )

    cfg = await resolve_config(db_session)

    assert cfg.project_ids == ["proj-1", "proj-2"]


@pytest.mark.integration
async def test_preset_env_conflict_raises(db_session: AsyncSession) -> None:
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        environment={"workspace_id": "ws", "project_ids": ["p"]},
    )

    with pytest.raises(ProjectConflictError, match="preset"):
        await resolve_config(db_session)


@pytest.mark.integration
async def test_parent_project_ids_fallback(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    cfg = await resolve_config(db_session, parent_project_ids=["parent-proj"])

    assert cfg.project_ids == ["parent-proj"]


@pytest.mark.integration
async def test_no_projects_pure_conversation(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    cfg = await resolve_config(db_session)

    assert cfg.project_ids == []


# ---------------------------------------------------------------------------
# Priority chain: request > override > preset > parent
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_request_projects_override_preset(db_session: AsyncSession) -> None:
    """Request-level project_ids win over preset environment."""
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        environment={"project_ids": ["preset-proj"]},
    )

    cfg = await resolve_config(db_session, project_ids=["request-proj"])

    assert cfg.project_ids == ["request-proj"]


@pytest.mark.integration
async def test_request_projects_override_parent(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    cfg = await resolve_config(
        db_session,
        project_ids=["request-proj"],
        parent_project_ids=["parent-proj"],
    )

    assert cfg.project_ids == ["request-proj"]


@pytest.mark.integration
async def test_override_env_overrides_parent(db_session: AsyncSession) -> None:
    await _create_preset(db_session, "p1", is_default=True)

    override = ConfigOverride(environment=EnvironmentSpec(project_ids=["ov-proj"]))
    cfg = await resolve_config(
        db_session,
        override=override,
        parent_project_ids=["parent-proj"],
    )

    assert cfg.project_ids == ["ov-proj"]


@pytest.mark.integration
async def test_preset_env_overrides_parent(db_session: AsyncSession) -> None:
    await _create_preset(
        db_session,
        "p1",
        is_default=True,
        environment={"project_ids": ["preset-proj"]},
    )

    cfg = await resolve_config(db_session, parent_project_ids=["parent-proj"])

    assert cfg.project_ids == ["preset-proj"]
