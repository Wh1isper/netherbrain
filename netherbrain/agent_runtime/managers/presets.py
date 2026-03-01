"""Preset CRUD operations.

Encapsulates all preset data access: create, list, get, update, delete,
and the ``is_default`` mutual exclusion rule.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Preset
from netherbrain.agent_runtime.models.api import PresetCreate, PresetUpdate


class DuplicatePresetError(ValueError):
    """Raised when a preset with the given ID already exists."""


class PresetNotFoundError(LookupError):
    """Raised when a preset is not found."""


def _to_row_kwargs(data: dict) -> dict:
    """Convert Pydantic-dumped dict to ORM column values.

    Nested Pydantic models (model, toolsets, environment, subagents) are stored
    as plain dicts/lists in JSONB columns.
    """
    for key in ("model", "environment", "subagents"):
        if key in data and hasattr(data[key], "model_dump"):
            data[key] = data[key].model_dump()
    if "toolsets" in data and isinstance(data["toolsets"], list):
        data["toolsets"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in data["toolsets"]]
    return data


async def create_preset(db: AsyncSession, body: PresetCreate) -> Preset:
    """Create a new agent preset.

    Raises ``DuplicatePresetError`` if the ID already exists.
    """
    preset_id = body.preset_id or str(uuid.uuid4())

    existing = await db.get(Preset, preset_id)
    if existing is not None:
        raise DuplicatePresetError(preset_id)

    if body.is_default:
        await _unset_all_defaults(db)

    row_data = _to_row_kwargs(body.model_dump(exclude={"preset_id"}))
    preset = Preset(preset_id=preset_id, **row_data)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


async def list_presets(db: AsyncSession) -> list[Preset]:
    """List all presets, ordered by creation time (newest first)."""
    result = await db.execute(select(Preset).order_by(Preset.created_at.desc()))
    return list(result.scalars().all())


async def get_preset(db: AsyncSession, preset_id: str) -> Preset:
    """Get a preset by ID.  Raises ``PresetNotFoundError`` if missing."""
    preset = await db.get(Preset, preset_id)
    if preset is None:
        raise PresetNotFoundError(preset_id)
    return preset


async def update_preset(db: AsyncSession, preset_id: str, body: PresetUpdate) -> Preset:
    """Partially update a preset.  Raises ``PresetNotFoundError`` if missing."""
    preset = await db.get(Preset, preset_id)
    if preset is None:
        raise PresetNotFoundError(preset_id)

    changes = _to_row_kwargs(body.model_dump(exclude_unset=True))
    if not changes:
        return preset

    if changes.get("is_default"):
        await _unset_all_defaults(db)

    for key, value in changes.items():
        setattr(preset, key, value)

    await db.commit()
    await db.refresh(preset)
    return preset


async def delete_preset(db: AsyncSession, preset_id: str) -> None:
    """Delete a preset.  Raises ``PresetNotFoundError`` if missing."""
    preset = await db.get(Preset, preset_id)
    if preset is None:
        raise PresetNotFoundError(preset_id)
    await db.delete(preset)
    await db.commit()


async def _unset_all_defaults(db: AsyncSession) -> None:
    """Set ``is_default=False`` on all presets."""
    await db.execute(update(Preset).where(Preset.is_default.is_(True)).values(is_default=False))
