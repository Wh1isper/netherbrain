"""Preset CRUD endpoints (RPC-style).

All write operations use POST; reads use GET.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from netherbrain.agent_runtime.db.tables import Preset
from netherbrain.agent_runtime.deps import DbSession
from netherbrain.agent_runtime.models.api import PresetCreate, PresetResponse, PresetUpdate

router = APIRouter(prefix="/presets", tags=["presets"])


def _preset_to_row_kwargs(data: dict) -> dict:
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


@router.post("/create", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(body: PresetCreate, db: DbSession) -> Preset:
    """Create a new agent preset."""
    preset_id = body.preset_id or str(uuid.uuid4())

    # Check for duplicate ID.
    existing = await db.get(Preset, preset_id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Preset '{preset_id}' already exists.")

    # If this preset is default, unset any current default.
    if body.is_default:
        await _unset_all_defaults(db)

    row_data = _preset_to_row_kwargs(body.model_dump(exclude={"preset_id"}))
    preset = Preset(preset_id=preset_id, **row_data)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.get("/list", response_model=list[PresetResponse])
async def list_presets(db: DbSession) -> list[Preset]:
    """List all agent presets, ordered by creation time (newest first)."""
    result = await db.execute(select(Preset).order_by(Preset.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{preset_id}/get", response_model=PresetResponse)
async def get_preset(preset_id: str, db: DbSession) -> Preset:
    """Get a single preset by ID."""
    preset = await db.get(Preset, preset_id)
    if preset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_id}' not found.")
    return preset


@router.post("/{preset_id}/update", response_model=PresetResponse)
async def update_preset(preset_id: str, body: PresetUpdate, db: DbSession) -> Preset:
    """Partially update an existing preset."""
    preset = await db.get(Preset, preset_id)
    if preset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_id}' not found.")

    changes = _preset_to_row_kwargs(body.model_dump(exclude_unset=True))
    if not changes:
        return preset

    # If setting this as default, unset others first.
    if changes.get("is_default"):
        await _unset_all_defaults(db)

    for key, value in changes.items():
        setattr(preset, key, value)

    await db.commit()
    await db.refresh(preset)
    return preset


@router.post("/{preset_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(preset_id: str, db: DbSession) -> None:
    """Delete a preset by ID."""
    preset = await db.get(Preset, preset_id)
    if preset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_id}' not found.")
    await db.delete(preset)
    await db.commit()


async def _unset_all_defaults(db: DbSession) -> None:
    """Set ``is_default=False`` on all presets."""
    await db.execute(update(Preset).where(Preset.is_default.is_(True)).values(is_default=False))
