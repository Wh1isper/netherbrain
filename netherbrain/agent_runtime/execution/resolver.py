"""Config resolver -- merges preset, per-request override, and workspace into
a single ResolvedConfig ready for the execution pipeline.

Resolution order (from spec/agent_runtime/02-configuration.md):

1. Load the referenced preset from PostgreSQL (or default preset if unspecified).
2. Merge per-request inline overrides (override wins at field level).
3. Resolve project list:
   - Request-level ``workspace_id`` / ``project_ids`` (highest priority)
   - Override environment ``workspace_id`` / ``project_ids``
   - Preset environment ``workspace_id`` / ``project_ids``
   - Parent session ``project_ids`` (continue / fork fallback)
   - Empty list (pure conversation mode)
4. Produce ``ResolvedConfig`` for execution.

Note: API key injection (step 4 in the spec) is handled by the SDK adapter,
not the resolver.  The resolver never touches secrets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import select

from netherbrain.agent_runtime.db.tables import Preset as PresetRow
from netherbrain.agent_runtime.db.tables import Workspace as WorkspaceRow
from netherbrain.agent_runtime.execution.mcp import McpConfig, build_mcp_config
from netherbrain.agent_runtime.models.enums import EnvironmentMode
from netherbrain.agent_runtime.models.preset import (
    EnvironmentSpec,
    McpServerSpec,
    ModelPreset,
    SubagentSpec,
    ToolConfigSpec,
    ToolsetSpec,
)
from netherbrain.agent_runtime.models.workspace import ProjectRef

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NoPresetError(LookupError):
    """No preset found (neither by ID nor a default)."""

    def __init__(self, preset_id: str | None = None) -> None:
        if preset_id is not None:
            super().__init__(f"Preset '{preset_id}' not found")
        else:
            super().__init__("No preset_id specified and no default preset configured")


class WorkspaceNotFoundError(LookupError):
    """Referenced workspace does not exist."""

    def __init__(self, workspace_id: str) -> None:
        super().__init__(f"Workspace '{workspace_id}' not found")


class ProjectConflictError(ValueError):
    """Both workspace_id and project_ids were specified at the same level."""

    def __init__(self, source: str = "request") -> None:
        super().__init__(f"workspace_id and project_ids are mutually exclusive at {source} level")


# ---------------------------------------------------------------------------
# Input / Output models
# ---------------------------------------------------------------------------


class ConfigOverride(BaseModel):
    """Per-request overrides.  Only explicitly set fields are applied."""

    model: ModelPreset | None = None
    system_prompt: str | None = None
    toolsets: list[ToolsetSpec] | None = None
    environment: EnvironmentSpec | None = None
    tool_config: ToolConfigSpec | None = None
    subagents: SubagentSpec | None = None
    mcp_servers: list[McpServerSpec] | None = None


class ResolvedConfig(BaseModel):
    """Fully resolved configuration for the execution pipeline.

    All ambiguity (default preset, workspace lookup, override merging) has been
    eliminated.  The adapter can map this directly to SDK primitives.
    """

    preset_id: str
    model: ModelPreset
    system_prompt: str
    toolsets: list[ToolsetSpec] = Field(default_factory=list)
    tool_config: ToolConfigSpec = Field(default_factory=ToolConfigSpec)
    subagents: SubagentSpec = Field(default_factory=SubagentSpec)

    # Resolved environment (flattened from EnvironmentSpec + workspace lookup)
    environment_mode: EnvironmentMode = EnvironmentMode.LOCAL
    project_ids: list[str] = Field(default_factory=list)
    project_descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of project_id -> description (from workspace ProjectRef).",
    )
    container_id: str | None = None
    container_workdir: str | None = None

    # External MCP configuration
    mcp: McpConfig = Field(default_factory=McpConfig)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_config(
    db: AsyncSession,
    *,
    preset_id: str | None = None,
    override: ConfigOverride | None = None,
    workspace_id: str | None = None,
    project_ids: list[str] | None = None,
    parent_project_ids: list[str] | None = None,
    parent_environment_mode: EnvironmentMode | None = None,
    parent_container_id: str | None = None,
    parent_container_workdir: str | None = None,
) -> ResolvedConfig:
    """Resolve a complete execution config from preset + override + workspace.

    Parameters
    ----------
    db:
        Async database session (per-request from DI).
    preset_id:
        Explicit preset to load.  If ``None``, the default preset is used.
    override:
        Per-request field-level overrides (wins over preset values).
    workspace_id:
        Request-level workspace reference (resolved from PG to project_ids).
        Mutually exclusive with ``project_ids``.
    project_ids:
        Request-level inline project list.
        Mutually exclusive with ``workspace_id``.
    parent_project_ids:
        Fallback project list from the parent session (continue / fork).
    parent_environment_mode:
        Fallback environment mode from the parent session.  Used when
        the preset does not explicitly set ``mode`` (async subagents).
    parent_container_id:
        Fallback container ID from the parent session.
    parent_container_workdir:
        Fallback container workdir from the parent session.

    Raises
    ------
    NoPresetError:
        Neither ``preset_id`` nor a default preset was found.
    WorkspaceNotFoundError:
        A referenced ``workspace_id`` does not exist in PG.
    ProjectConflictError:
        Both ``workspace_id`` and ``project_ids`` are specified at the
        same level (request or override or preset environment).
    """
    # -- Validate request-level mutual exclusion -------------------------------
    if workspace_id is not None and project_ids is not None:
        raise ProjectConflictError("request")

    # -- 1. Load preset --------------------------------------------------------
    preset = await _load_preset(db, preset_id)

    # -- 2. Merge overrides ----------------------------------------------------
    model = _first(override and override.model, ModelPreset(**preset.model))
    system_prompt = _first(override and override.system_prompt, preset.system_prompt)
    toolsets = _first(
        override and override.toolsets,
        [ToolsetSpec(**t) for t in preset.toolsets],
    )
    subagents_raw = _first(
        override and override.subagents,
        SubagentSpec(**preset.subagents),
    )
    tool_config_raw = _first(
        override and override.tool_config,
        ToolConfigSpec(**preset.tool_config),
    )

    # Environment: merge mode/container settings from override, preset, or parent.
    # The raw preset dict is checked so we can distinguish "explicitly set to LOCAL"
    # from "not specified (default)".  Unspecified fields fall back to parent values
    # (important for async subagents inheriting the spawner's environment).
    env_override = override.environment if override else None
    preset_env_dict = preset.environment  # raw JSONB dict
    env_preset = EnvironmentSpec(**preset_env_dict)

    environment_mode = _resolve_env_field(
        env_override and env_override.mode,
        preset_env_dict,
        "mode",
        env_preset.mode,
        parent_environment_mode,
        EnvironmentMode.LOCAL,
    )
    container_id = _resolve_env_field(
        env_override and env_override.container_id,
        preset_env_dict,
        "container_id",
        env_preset.container_id,
        parent_container_id,
        None,
    )
    container_workdir = _resolve_env_field(
        env_override and env_override.container_workdir,
        preset_env_dict,
        "container_workdir",
        env_preset.container_workdir,
        parent_container_workdir,
        None,
    )

    # -- 3. Resolve project_ids ------------------------------------------------
    resolved_projects, resolved_descriptions = await _resolve_projects(
        db,
        request_workspace_id=workspace_id,
        request_project_ids=project_ids,
        override_env=env_override,
        preset_env=env_preset,
        parent_project_ids=parent_project_ids,
    )

    # -- 4. Merge MCP servers (override replaces preset list entirely) ----------
    mcp_servers = _first(
        override and override.mcp_servers,
        [McpServerSpec(**s) for s in preset.mcp_servers] if preset.mcp_servers else [],
    )

    # -- 5. Build ResolvedConfig -----------------------------------------------
    return ResolvedConfig(
        preset_id=preset.preset_id,
        model=model,
        system_prompt=system_prompt,
        toolsets=toolsets,
        tool_config=tool_config_raw,
        subagents=subagents_raw,
        environment_mode=environment_mode,
        project_ids=resolved_projects,
        project_descriptions=resolved_descriptions,
        container_id=container_id,
        container_workdir=container_workdir,
        mcp=build_mcp_config(mcp_servers),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_preset(db: AsyncSession, preset_id: str | None) -> PresetRow:
    """Load a preset by ID, or fall back to the default preset.

    Raises ``NoPresetError`` if nothing is found.
    """
    if preset_id is not None:
        row = await db.get(PresetRow, preset_id)
        if row is None:
            raise NoPresetError(preset_id)
        return row

    # Find the default preset.
    stmt = select(PresetRow).where(PresetRow.is_default.is_(True)).limit(1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise NoPresetError()
    return row


async def _resolve_workspace(db: AsyncSession, workspace_id: str) -> tuple[list[str], dict[str, str]]:
    """Resolve a workspace_id to its project list and descriptions.

    Returns ``(project_ids, descriptions)`` where descriptions is a dict
    mapping project_id -> description for projects that have one.

    Raises ``WorkspaceNotFoundError`` if the workspace does not exist.
    """
    row = await db.get(WorkspaceRow, workspace_id)
    if row is None:
        raise WorkspaceNotFoundError(workspace_id)

    project_ids: list[str] = []
    descriptions: dict[str, str] = {}
    for entry in row.projects:
        ref = ProjectRef(**entry) if isinstance(entry, dict) else ProjectRef(id=entry)
        project_ids.append(ref.id)
        if ref.description:
            descriptions[ref.id] = ref.description

    return project_ids, descriptions


async def _resolve_projects(
    db: AsyncSession,
    *,
    request_workspace_id: str | None,
    request_project_ids: list[str] | None,
    override_env: EnvironmentSpec | None,
    preset_env: EnvironmentSpec,
    parent_project_ids: list[str] | None,
) -> tuple[list[str], dict[str, str]]:
    """Walk the priority chain to produce a final project_ids list and descriptions.

    Returns ``(project_ids, descriptions)`` where descriptions is populated
    only when projects are resolved from a workspace.

    Priority (highest first):
    1. Request-level workspace_id / project_ids
    2. Override environment workspace_id / project_ids
    3. Preset environment workspace_id / project_ids
    4. Parent session project_ids (continue / fork)
    5. Empty list (pure conversation mode)
    """
    # Level 1: request params (already validated for mutual exclusion)
    if request_workspace_id is not None:
        return await _resolve_workspace(db, request_workspace_id)
    if request_project_ids is not None:
        return request_project_ids, {}

    # Level 2: override environment
    if override_env is not None:
        result = await _resolve_env_projects(db, override_env, "override")
        if result is not None:
            return result

    # Level 3: preset environment
    result = await _resolve_env_projects(db, preset_env, "preset")
    if result is not None:
        return result

    # Level 4: parent session fallback
    if parent_project_ids is not None:
        return parent_project_ids, {}

    # Level 5: no projects (pure conversation mode)
    return [], {}


async def _resolve_env_projects(
    db: AsyncSession,
    env: EnvironmentSpec,
    source: str,
) -> tuple[list[str], dict[str, str]] | None:
    """Resolve project_ids from an EnvironmentSpec, or return None if unset.

    Returns ``(project_ids, descriptions)`` or ``None``.
    Raises ``ProjectConflictError`` if both workspace_id and project_ids are set.
    """
    has_workspace = env.workspace_id is not None
    has_projects = env.project_ids is not None

    if has_workspace and has_projects:
        raise ProjectConflictError(source)

    if has_workspace:
        return await _resolve_workspace(db, env.workspace_id)  # type: ignore[arg-type]
    if has_projects:
        return list(env.project_ids), {}  # type: ignore[arg-type]

    return None


def _first[T](override: T | None, default: T) -> T:
    """Return the override if not None, otherwise the default."""
    return override if override is not None else default


def _resolve_env_field[T](
    override_val: T | None,
    preset_dict: dict,
    preset_key: str,
    preset_val: T,
    parent_val: T | None,
    default: T,
) -> T:
    """Resolve an environment field with parent fallback.

    Priority: override -> preset (if explicitly set) -> parent -> default.
    Checks the raw preset dict for key presence to distinguish
    'explicitly set' from 'using Pydantic default'.
    """
    if override_val is not None:
        return override_val
    if preset_key in preset_dict:
        return preset_val  # type: ignore[return-value]
    if parent_val is not None:
        return parent_val
    return default
