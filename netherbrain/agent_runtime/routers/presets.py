"""Preset CRUD endpoints (RPC-style).

Thin HTTP adapter -- delegates all business logic to the preset manager.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from netherbrain.agent_runtime.deps import DbSession
from netherbrain.agent_runtime.managers.presets import (
    DuplicatePresetError,
    PresetNotFoundError,
    create_preset,
    delete_preset,
    get_preset,
    list_presets,
    update_preset,
)
from netherbrain.agent_runtime.models.api import PresetCreate, PresetResponse, PresetUpdate

router = APIRouter(prefix="/presets", tags=["presets"])


@router.post("/create", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
async def handle_create_preset(body: PresetCreate, db: DbSession) -> object:
    try:
        return await create_preset(db, body)
    except DuplicatePresetError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Preset '{exc}' already exists.") from None


@router.get("/list", response_model=list[PresetResponse])
async def handle_list_presets(db: DbSession) -> list:
    return await list_presets(db)


@router.get("/{preset_id}/get", response_model=PresetResponse)
async def handle_get_preset(preset_id: str, db: DbSession) -> object:
    try:
        return await get_preset(db, preset_id)
    except PresetNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_id}' not found.") from None


@router.post("/{preset_id}/update", response_model=PresetResponse)
async def handle_update_preset(preset_id: str, body: PresetUpdate, db: DbSession) -> object:
    try:
        return await update_preset(db, preset_id, body)
    except PresetNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_id}' not found.") from None


@router.post("/{preset_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def handle_delete_preset(preset_id: str, db: DbSession) -> None:
    try:
        await delete_preset(db, preset_id)
    except PresetNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_id}' not found.") from None
