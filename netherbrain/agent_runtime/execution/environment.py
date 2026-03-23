"""Environment setup for agent execution.

Resolves project_ids to real filesystem paths, auto-creates directories,
and constructs the SDK Environment for the execution pipeline.

Three environment modes are supported:

**Conversation-only mode** (no projects):
    No project directories.  The agent operates as a pure conversational
    assistant with only a temporary directory.  Filesystem and shell
    tools are stripped by the runtime.  Uses ``LocalEnvironment`` with
    no ``default_path``.

**Local mode** (``EnvironmentMode.LOCAL``):
    Shell and file operations run directly on the host.  The agent sees
    real filesystem paths (e.g., ``{DATA_ROOT}/projects/{project_id}/``).
    Uses ``LocalEnvironment`` from the SDK.

**Sandbox mode** (``EnvironmentMode.SANDBOX``):
    Shell commands execute inside a Docker container via ``docker exec``.
    File operations run on the host but are presented through a virtual
    path space (e.g., ``/workspace/{project_id}/``).  Both the file
    operator and the shell see the same virtual paths, giving the agent
    a symmetric view.  Uses ``SandboxEnvironment`` from the SDK.

    The runtime only attaches to an existing container (``container_id``
    is required).  Container lifecycle is managed externally by the user.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from y_agent_environment import ResourceFactory
from y_agent_environment.resources import BaseResource
from ya_agent_sdk.environment.local import LocalEnvironment, VirtualMount
from ya_agent_sdk.environment.sandbox import SandboxEnvironment

from netherbrain.agent_runtime.execution.resolver import ResolvedConfig
from netherbrain.agent_runtime.models.enums import EnvironmentMode
from netherbrain.agent_runtime.settings import NetherSettings

if TYPE_CHECKING:
    from y_agent_environment.resources import ResourceRegistryState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CONTAINER_WORKDIR = "/workspace"
"""Default virtual root path presented to the agent in sandbox mode."""

PROJECT_DESCRIPTIONS_RESOURCE_KEY = "project-descriptions"
"""Resource registry key for project descriptions."""


# ---------------------------------------------------------------------------
# Project descriptions resource
# ---------------------------------------------------------------------------


class ProjectDescriptionsResource(BaseResource):
    """InstructableResource that injects project descriptions into agent context.

    Registered on the Environment's ResourceRegistry so descriptions appear
    inside ``<environment-context><resources>`` alongside file trees.
    """

    def __init__(self, descriptions: dict[str, str]) -> None:
        self._descriptions = descriptions

    async def close(self) -> None:
        pass  # Stateless, nothing to clean up.

    async def get_context_instructions(self) -> str | None:
        if not self._descriptions:
            return None
        lines = [f"- {pid}: {desc}" for pid, desc in self._descriptions.items()]
        return "Project descriptions:\n" + "\n".join(lines)


def _build_resource_factories(
    project_descriptions: dict[str, str] | None,
) -> dict[str, ResourceFactory] | None:
    """Build resource factories dict for Environment construction.

    Returns ``None`` if no resources need to be registered.
    """
    if not project_descriptions:
        return None

    # Capture descriptions in closure for the factory.
    descs = dict(project_descriptions)

    async def _create_descriptions(env: Any) -> ProjectDescriptionsResource:
        return ProjectDescriptionsResource(descs)

    return {PROJECT_DESCRIPTIONS_RESOURCE_KEY: _create_descriptions}


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
        virtual_root: Path | None = None,
    ) -> None:
        self.virtual_root = virtual_root or Path(DEFAULT_CONTAINER_WORKDIR)
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
        """Virtual path for a project: ``{virtual_root}/{project_id}/``."""
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
    virtual_root = Path(config.container_workdir) if config.container_workdir else None
    return ProjectPaths(
        data_root=Path(settings.data_root),
        prefix=settings.data_prefix,
        project_ids=config.project_ids,
        virtual_root=virtual_root,
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

    When no projects are configured, returns a ``LocalEnvironment`` with
    only a temporary directory (no project paths, no CWD access).

    Project descriptions from workspace ``ProjectRef`` entries are injected
    via a ``ProjectDescriptionsResource`` on the Environment's
    ``ResourceRegistry``.  The agent sees them inside
    ``<environment-context><resources>``.

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
    resource_factories = _build_resource_factories(config.project_descriptions)

    if not paths.has_projects:
        env = LocalEnvironment(
            enable_tmp_dir=True,
            resource_factories=resource_factories,
        )
        return env, paths

    # Ensure project directories exist on disk.
    paths.ensure_directories()

    if config.environment_mode == EnvironmentMode.LOCAL:
        env = _create_local_environment(paths, resource_state, resource_factories)
    else:
        env = _create_sandbox_environment(config, paths, resource_state, resource_factories)

    return env, paths


def _create_local_environment(
    paths: ProjectPaths,
    resource_state: ResourceRegistryState | None,
    resource_factories: dict[str, ResourceFactory] | None,
) -> LocalEnvironment:
    """Create a local-mode environment.

    Uses ``LocalEnvironment`` with real host paths.  The agent sees
    the actual filesystem paths directly.
    """
    default_path = paths.default_real_path
    extra_paths = [paths.real_path(pid) for pid in paths.extra_project_ids]

    return LocalEnvironment(
        default_path=default_path,
        allowed_paths=extra_paths or None,
        resource_state=resource_state,
        resource_factories=resource_factories,
    )


def _create_sandbox_environment(
    config: ResolvedConfig,
    paths: ProjectPaths,
    resource_state: ResourceRegistryState | None,
    resource_factories: dict[str, ResourceFactory] | None,
) -> SandboxEnvironment:
    """Create a sandbox-mode environment.

    Uses ``SandboxEnvironment`` with:
    - ``VirtualLocalFileOperator``: file I/O on host with virtual path mapping
    - ``DockerShell``: shell commands via ``docker exec`` in the container

    The runtime attaches to the container specified by ``container_id``
    and does not manage its lifecycle (no create/start/stop/remove).
    The container must already be running (or in a startable state).

    The user is responsible for mounting project directories into the
    container at the appropriate paths (matching ``container_workdir``).
    """
    workdir = config.container_workdir or DEFAULT_CONTAINER_WORKDIR

    # Build mount mappings: host project dirs -> virtual paths inside container
    mounts = [
        VirtualMount(
            host_path=paths.real_path(pid),
            virtual_path=Path(workdir) / pid,
        )
        for pid in paths.project_ids
    ]

    # Default working directory is the first project's virtual path
    default_project = paths.default_project_id
    work_dir = f"{workdir}/{default_project}" if default_project else workdir

    return SandboxEnvironment(
        mounts=mounts,
        work_dir=work_dir,
        container_id=config.container_id,
        cleanup_on_exit=False,
        resource_state=resource_state,
        resource_factories=resource_factories,
    )
