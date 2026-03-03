"""Seed data loader -- upserts presets and workspaces from a TOML file.

Reads a declarative TOML file and synchronises its contents into PostgreSQL
using upsert semantics: create if missing, update if exists.

The seed file is the "source of truth" for the entities it declares.
Entities removed from the file are NOT deleted from the database.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Preset, Workspace
from netherbrain.agent_runtime.managers.presets import _to_row_kwargs, _unset_all_defaults
from netherbrain.agent_runtime.models.api import PresetCreate, WorkspaceCreate

logger = logging.getLogger(__name__)


@dataclass
class SeedResult:
    """Summary of a seed operation."""

    presets_created: int = 0
    presets_updated: int = 0
    workspaces_created: int = 0
    workspaces_updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.presets_created + self.presets_updated + self.workspaces_created + self.workspaces_updated


def load_seed_file(path: str | Path) -> dict:
    """Parse a seed TOML file and return raw data.

    Raises ``FileNotFoundError`` if the file does not exist.
    Raises ``tomllib.TOMLDecodeError`` on invalid TOML.
    """
    p = Path(path)
    if not p.is_file():
        msg = f"Seed file not found: {p}"
        raise FileNotFoundError(msg)
    with p.open("rb") as f:
        return tomllib.load(f)


async def apply_seed(db: AsyncSession, data: dict) -> SeedResult:
    """Apply parsed seed data to the database.

    Upserts presets and workspaces. Returns a summary of changes.
    """
    result = SeedResult()

    # -- Presets ----------------------------------------------------------------
    for raw_preset in data.get("presets", []):
        try:
            await _upsert_preset(db, raw_preset, result)
        except Exception as exc:
            pid = raw_preset.get("preset_id", "<unknown>")
            result.errors.append(f"preset '{pid}': {exc}")
            logger.warning("Seed: failed to upsert preset '%s': %s", pid, exc)

    # -- Workspaces ------------------------------------------------------------
    for raw_workspace in data.get("workspaces", []):
        try:
            await _upsert_workspace(db, raw_workspace, result)
        except Exception as exc:
            wid = raw_workspace.get("workspace_id", "<unknown>")
            result.errors.append(f"workspace '{wid}': {exc}")
            logger.warning("Seed: failed to upsert workspace '%s': %s", wid, exc)

    return result


async def _upsert_preset(db: AsyncSession, raw: dict, result: SeedResult) -> None:
    """Create or update a single preset from seed data."""
    # Validate through Pydantic (reuses API schema for consistency).
    body = PresetCreate(**raw)
    preset_id = body.preset_id
    if not preset_id:
        msg = "preset_id is required in seed file"
        raise ValueError(msg)

    existing = await db.get(Preset, preset_id)

    if body.is_default:
        await _unset_all_defaults(db)

    row_data = _to_row_kwargs(body.model_dump(exclude={"preset_id"}))

    if existing is None:
        # Create.
        preset = Preset(preset_id=preset_id, **row_data)
        db.add(preset)
        await db.commit()
        result.presets_created += 1
        logger.info("Seed: created preset '%s'", preset_id)
    else:
        # Update.
        for key, value in row_data.items():
            setattr(existing, key, value)
        await db.commit()
        result.presets_updated += 1
        logger.info("Seed: updated preset '%s'", preset_id)


async def _upsert_workspace(db: AsyncSession, raw: dict, result: SeedResult) -> None:
    """Create or update a single workspace from seed data."""
    body = WorkspaceCreate(**raw)
    workspace_id = body.workspace_id
    if not workspace_id:
        msg = "workspace_id is required in seed file"
        raise ValueError(msg)

    existing = await db.get(Workspace, workspace_id)

    if existing is None:
        # Create.
        workspace = Workspace(
            workspace_id=workspace_id,
            name=body.name,
            projects=body.projects,
            metadata_=body.metadata,
        )
        db.add(workspace)
        await db.commit()
        result.workspaces_created += 1
        logger.info("Seed: created workspace '%s'", workspace_id)
    else:
        # Update.
        if body.name is not None:
            existing.name = body.name
        existing.projects = body.projects
        if body.metadata is not None:
            existing.metadata_ = body.metadata
        await db.commit()
        result.workspaces_updated += 1
        logger.info("Seed: updated workspace '%s'", workspace_id)
