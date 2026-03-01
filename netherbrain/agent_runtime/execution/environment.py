"""Environment setup for agent execution.

Resolves project_ids to real filesystem paths, auto-creates directories,
and constructs the SDK Environment for the execution pipeline.

Virtual Workspace Model
-----------------------

The agent operates in a virtual workspace rooted at ``/workspace/``:

- ``/workspace/``                 -> default project (CWD)
- ``/workspace/{project_id}/``    -> additional projects

Real paths on the host:

- ``{data_root}/{prefix}/projects/{project_id}/``

Path translation is handled by a VirtualFileOperator that maps virtual
paths to real paths on every file operation.  The agent never sees the
real host path.

Shell modes:

- **local**: Shell runs on the host with CWD set to the real project path.
  The agent may see the real path via ``pwd`` but all file tool outputs
  use virtual paths.
- **docker**: Shell runs inside the container via ``docker exec``.
  The container mounts ``{data_root}/projects/`` as ``/workspace/``,
  so the shell naturally sees ``/workspace/`` paths.
  File operations still happen on the host via VirtualFileOperator.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ya_agent_sdk.environment.local import LocalEnvironment

from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
from netherbrain.agent_runtime.models.enums import ShellMode
from netherbrain.agent_runtime.settings import NetherSettings

if TYPE_CHECKING:
    from y_agent_environment.resources import ResourceRegistryState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIRTUAL_WORKSPACE_ROOT = Path("/workspace")
"""Virtual root path presented to the agent."""


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


class ProjectPaths:
    """Resolved project paths (both virtual and real).

    Constructed from ``ResolvedConfig.project_ids`` and settings.
    Used by the environment factory to configure FileOperator and Shell.
    """

    def __init__(
        self,
        *,
        data_root: Path,
        prefix: str | None,
        project_ids: list[str],
        virtual_root: Path = VIRTUAL_WORKSPACE_ROOT,
    ) -> None:
        self.virtual_root = virtual_root
        self.project_ids = project_ids

        # Build real base: {data_root}/{prefix}/projects/ or {data_root}/projects/
        base = data_root
        if prefix:
            base = base / prefix
        self._projects_base = base / "projects"

    @property
    def has_projects(self) -> bool:
        return len(self.project_ids) > 0

    @property
    def default_project_id(self) -> str | None:
        """First project_id is the default (CWD)."""
        return self.project_ids[0] if self.project_ids else None

    @property
    def extra_project_ids(self) -> list[str]:
        """Additional project_ids beyond the default."""
        return self.project_ids[1:] if len(self.project_ids) > 1 else []

    def real_path(self, project_id: str) -> Path:
        """Real host path for a project: ``{base}/projects/{project_id}/``."""
        return self._projects_base / project_id

    def virtual_path(self, project_id: str) -> Path:
        """Virtual path for a project: ``/workspace/{project_id}/``."""
        return self.virtual_root / project_id

    @property
    def default_real_path(self) -> Path | None:
        """Real path for the default project (CWD)."""
        pid = self.default_project_id
        return self.real_path(pid) if pid else None

    @property
    def default_virtual_path(self) -> Path | None:
        """Virtual path for the default project (CWD)."""
        pid = self.default_project_id
        return self.virtual_path(pid) if pid else None

    @property
    def all_real_paths(self) -> list[Path]:
        """All real project paths in order."""
        return [self.real_path(pid) for pid in self.project_ids]

    @property
    def all_virtual_paths(self) -> list[Path]:
        """All virtual project paths in order."""
        return [self.virtual_path(pid) for pid in self.project_ids]

    @property
    def path_mapping(self) -> dict[str, Path]:
        """Virtual path string -> real Path mapping for all projects.

        Used by VirtualFileOperator to translate paths.
        """
        return {str(self.virtual_path(pid)): self.real_path(pid) for pid in self.project_ids}

    def ensure_directories(self) -> None:
        """Create all project directories on disk (idempotent)."""
        for real_path in self.all_real_paths:
            real_path.mkdir(parents=True, exist_ok=True)


def resolve_project_paths(
    config: ResolvedConfig,
    settings: NetherSettings,
) -> ProjectPaths:
    """Build ``ProjectPaths`` from resolved config and settings."""
    return ProjectPaths(
        data_root=Path(settings.data_root),
        prefix=settings.data_prefix,
        project_ids=config.project_ids,
    )


# ---------------------------------------------------------------------------
# Environment factory
# ---------------------------------------------------------------------------


def create_environment(
    config: ResolvedConfig,
    settings: NetherSettings,
    *,
    resource_state: ResourceRegistryState | None = None,
) -> tuple:
    """Create an SDK Environment from resolved config.

    Returns ``(environment, project_paths)`` so the caller can access
    path metadata for session commit.

    The environment is NOT entered yet -- the caller must use it as an
    async context manager (or pass it to ``create_agent(env=...)``).

    Parameters
    ----------
    config:
        Fully resolved execution config (from ``resolve_config``).
    settings:
        Service settings (data_root, data_prefix).
    resource_state:
        Optional resource state to restore (from parent session).

    Returns
    -------
    tuple of (Environment, ProjectPaths)
    """
    paths = resolve_project_paths(config, settings)

    if not paths.has_projects:
        # Pure conversation mode: no file system access.
        # Use a minimal environment with no allowed paths.
        env = LocalEnvironment(enable_tmp_dir=True)
        return env, paths

    # Ensure project directories exist on disk.
    paths.ensure_directories()

    if config.shell_mode == ShellMode.LOCAL:
        env = _create_local_environment(paths, resource_state)
    else:
        env = _create_docker_environment(config, paths, resource_state)

    return env, paths


def _create_local_environment(
    paths: ProjectPaths,
    resource_state: ResourceRegistryState | None,
) -> object:
    """Create a local-mode environment.

    TODO: Replace LocalEnvironment with VirtualLocalEnvironment once the
    SDK provides VirtualFileOperator. For now, uses real paths with
    LocalEnvironment. The virtual path mapping will be added when the SDK
    (or this module) implements the translation layer.
    """
    default_path = paths.default_real_path
    extra_paths = [paths.real_path(pid) for pid in paths.extra_project_ids]

    return LocalEnvironment(
        default_path=default_path,
        allowed_paths=extra_paths or None,
        resource_state=resource_state,
    )


def _create_docker_environment(
    config: ResolvedConfig,
    paths: ProjectPaths,
    resource_state: ResourceRegistryState | None,
) -> object:
    """Create a docker-mode environment.

    File operations: VirtualFileOperator on host (virtual -> real translation).
    Shell: DockerShell targeting the configured container.

    The container is expected to mount the projects directory as /workspace/:
        docker run -v {data_root}/projects:/workspace ...

    TODO: Implement DockerShell integration. For now, raises NotImplementedError.
    """
    msg = f"Docker mode not yet implemented (container_id={config.container_id}). Use shell_mode=local for now."
    raise NotImplementedError(msg)
