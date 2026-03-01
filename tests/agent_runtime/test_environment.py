"""Unit tests for environment setup (path resolution, no DB required)."""

from __future__ import annotations

from pathlib import Path

from netherbrain.agent_runtime.execution.environment import (
    VIRTUAL_WORKSPACE_ROOT,
    ProjectPaths,
)


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
    assert paths.default_virtual_path == VIRTUAL_WORKSPACE_ROOT / "my-proj"

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
