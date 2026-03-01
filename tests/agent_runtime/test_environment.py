"""Unit tests for environment setup (path resolution, no DB required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ya_agent_sdk.environment.local import LocalEnvironment
from ya_agent_sdk.environment.sandbox import SandboxEnvironment

from netherbrain.agent_runtime.execution.environment import (
    DEFAULT_CONTAINER_WORKDIR,
    ProjectPaths,
    create_environment,
)
from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
from netherbrain.agent_runtime.models.enums import EnvironmentMode
from netherbrain.agent_runtime.models.preset import ModelPreset, SubagentSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.data_root = str(tmp_path)
    settings.data_prefix = None
    return settings


def _make_config(**overrides) -> ResolvedConfig:
    defaults = {
        "preset_id": "test",
        "model": ModelPreset(name="openai:gpt-4o"),
        "system_prompt": "test",
        "toolsets": [],
        "subagents": SubagentSpec(),
        "environment_mode": EnvironmentMode.LOCAL,
        "project_ids": ["proj-a"],
    }
    defaults.update(overrides)
    return ResolvedConfig(**defaults)


def test_project_paths_basic() -> None:
    paths = ProjectPaths(
        data_root=Path("/data"),
        prefix=None,
        project_ids=["my-proj", "shared-lib"],
    )

    assert paths.has_projects is True
    assert paths.default_project_id == "my-proj"
    assert paths.extra_project_ids == ["shared-lib"]

    assert paths.default_real_path == Path("/data/projects/my-proj")
    assert paths.default_virtual_path == Path(DEFAULT_CONTAINER_WORKDIR) / "my-proj"

    assert paths.real_path("my-proj") == Path("/data/projects/my-proj")
    assert paths.real_path("shared-lib") == Path("/data/projects/shared-lib")

    assert paths.virtual_path("my-proj") == Path("/workspace/my-proj")
    assert paths.virtual_path("shared-lib") == Path("/workspace/shared-lib")


def test_project_paths_with_prefix() -> None:
    paths = ProjectPaths(
        data_root=Path("/data"),
        prefix="tenant-a",
        project_ids=["proj"],
    )

    assert paths.real_path("proj") == Path("/data/tenant-a/projects/proj")
    assert paths.virtual_path("proj") == Path("/workspace/proj")


def test_project_paths_no_projects() -> None:
    paths = ProjectPaths(
        data_root=Path("/data"),
        prefix=None,
        project_ids=[],
    )

    assert paths.has_projects is False
    assert paths.default_project_id is None
    assert paths.default_real_path is None
    assert paths.default_virtual_path is None
    assert paths.extra_project_ids == []
    assert paths.all_real_paths == []
    assert paths.all_virtual_paths == []
    assert paths.path_mapping == {}


def test_project_paths_single_project() -> None:
    paths = ProjectPaths(
        data_root=Path("/data"),
        prefix=None,
        project_ids=["solo"],
    )

    assert paths.has_projects is True
    assert paths.default_project_id == "solo"
    assert paths.extra_project_ids == []
    assert len(paths.all_real_paths) == 1


def test_project_paths_mapping() -> None:
    paths = ProjectPaths(
        data_root=Path("/data"),
        prefix="ns",
        project_ids=["a", "b", "c"],
    )

    mapping = paths.path_mapping

    assert mapping["/workspace/a"] == Path("/data/ns/projects/a")
    assert mapping["/workspace/b"] == Path("/data/ns/projects/b")
    assert mapping["/workspace/c"] == Path("/data/ns/projects/c")
    assert len(mapping) == 3


def test_ensure_directories(tmp_path: Path) -> None:
    paths = ProjectPaths(
        data_root=tmp_path,
        prefix=None,
        project_ids=["alpha", "beta"],
    )

    # Directories should not exist yet.
    assert not (tmp_path / "projects" / "alpha").exists()
    assert not (tmp_path / "projects" / "beta").exists()

    paths.ensure_directories()

    assert (tmp_path / "projects" / "alpha").is_dir()
    assert (tmp_path / "projects" / "beta").is_dir()

    # Idempotent: calling again should not raise.
    paths.ensure_directories()


def test_ensure_directories_with_prefix(tmp_path: Path) -> None:
    paths = ProjectPaths(
        data_root=tmp_path,
        prefix="tenant-x",
        project_ids=["proj"],
    )

    paths.ensure_directories()

    assert (tmp_path / "tenant-x" / "projects" / "proj").is_dir()


# ---------------------------------------------------------------------------
# create_environment factory tests
# ---------------------------------------------------------------------------


def test_create_environment_no_projects(tmp_path: Path) -> None:
    """No project_ids -> minimal LocalEnvironment (pure conversation mode)."""
    config = _make_config(project_ids=[])
    settings = _make_settings(tmp_path)

    env, paths = create_environment(config, settings)

    assert isinstance(env, LocalEnvironment)
    assert not paths.has_projects


def test_create_environment_local_mode(tmp_path: Path) -> None:
    """Local mode -> LocalEnvironment with real project paths."""
    config = _make_config(
        environment_mode=EnvironmentMode.LOCAL,
        project_ids=["proj-a", "proj-b"],
    )
    settings = _make_settings(tmp_path)

    env, paths = create_environment(config, settings)

    assert isinstance(env, LocalEnvironment)
    assert paths.has_projects
    assert paths.default_project_id == "proj-a"
    # Directories should be auto-created
    assert (tmp_path / "projects" / "proj-a").is_dir()
    assert (tmp_path / "projects" / "proj-b").is_dir()


def test_create_environment_sandbox_mode(tmp_path: Path) -> None:
    """Sandbox mode -> SandboxEnvironment with correct mounts and container config."""
    config = _make_config(
        environment_mode=EnvironmentMode.SANDBOX,
        project_ids=["proj-a", "proj-b"],
        container_id="test-container-123",
        container_workdir="/workspace",
    )
    settings = _make_settings(tmp_path)

    env, _paths = create_environment(config, settings)

    assert isinstance(env, SandboxEnvironment)
    # Verify container config
    assert env._container_id == "test-container-123"
    assert env._cleanup_on_exit is False
    # Verify work_dir points to default project
    assert env._work_dir == "/workspace/proj-a"
    # Verify mounts: one per project
    assert len(env._mounts) == 2
    assert env._mounts[0].host_path == (tmp_path / "projects" / "proj-a").resolve()
    assert env._mounts[0].virtual_path == Path("/workspace/proj-a")
    assert env._mounts[1].host_path == (tmp_path / "projects" / "proj-b").resolve()
    assert env._mounts[1].virtual_path == Path("/workspace/proj-b")
    # Directories should be auto-created on host
    assert (tmp_path / "projects" / "proj-a").is_dir()
    assert (tmp_path / "projects" / "proj-b").is_dir()


def test_create_environment_sandbox_custom_workdir(tmp_path: Path) -> None:
    """Sandbox mode respects custom container_workdir."""
    config = _make_config(
        environment_mode=EnvironmentMode.SANDBOX,
        project_ids=["myproj"],
        container_id="ctr-1",
        container_workdir="/app",
    )
    settings = _make_settings(tmp_path)

    env, _paths = create_environment(config, settings)

    assert isinstance(env, SandboxEnvironment)
    assert env._work_dir == "/app/myproj"
    assert env._mounts[0].virtual_path == Path("/app/myproj")


def test_create_environment_sandbox_single_project(tmp_path: Path) -> None:
    """Sandbox with single project -> one mount, work_dir = that project."""
    config = _make_config(
        environment_mode=EnvironmentMode.SANDBOX,
        project_ids=["solo"],
        container_id="ctr-solo",
    )
    settings = _make_settings(tmp_path)

    env, _paths = create_environment(config, settings)

    assert isinstance(env, SandboxEnvironment)
    assert len(env._mounts) == 1
    assert env._work_dir == f"{DEFAULT_CONTAINER_WORKDIR}/solo"


def test_create_environment_local_with_prefix(tmp_path: Path) -> None:
    """Local mode with data_prefix creates correct nested paths."""
    config = _make_config(
        environment_mode=EnvironmentMode.LOCAL,
        project_ids=["proj"],
    )
    settings = _make_settings(tmp_path)
    settings.data_prefix = "tenant-x"

    env, _paths = create_environment(config, settings)

    assert isinstance(env, LocalEnvironment)
    assert (tmp_path / "tenant-x" / "projects" / "proj").is_dir()
