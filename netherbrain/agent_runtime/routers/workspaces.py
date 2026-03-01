"""Workspace CRUD endpoints (RPC-style).

Thin HTTP adapter -- delegates all business logic to the workspace manager.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from netherbrain.agent_runtime.deps import DbSession
from netherbrain.agent_runtime.managers.workspaces import (
    DuplicateWorkspaceError,
    WorkspaceNotFoundError,
    create_workspace,
    delete_workspace,
    get_workspace,
    list_workspaces,
    update_workspace,
)
from netherbrain.agent_runtime.models.api import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("/create", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def handle_create_workspace(body: WorkspaceCreate, db: DbSession) -> object:
    try:
        return await create_workspace(db, body)
    except DuplicateWorkspaceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Workspace '{exc}' already exists.") from None


@router.get("/list", response_model=list[WorkspaceResponse])
async def handle_list_workspaces(
    db: DbSession,
    metadata_contains: str | None = Query(
        None,
        description='JSON string for JSONB containment filter (@>). Example: \'{"source": "webui"}\'.',
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list:
    try:
        return await list_workspaces(db, metadata_contains=metadata_contains, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None


@router.get("/{workspace_id}/get", response_model=WorkspaceResponse)
async def handle_get_workspace(workspace_id: str, db: DbSession) -> object:
    try:
        return await get_workspace(db, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Workspace '{workspace_id}' not found.") from None


@router.post("/{workspace_id}/update", response_model=WorkspaceResponse)
async def handle_update_workspace(workspace_id: str, body: WorkspaceUpdate, db: DbSession) -> object:
    try:
        return await update_workspace(db, workspace_id, body)
    except WorkspaceNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Workspace '{workspace_id}' not found.") from None


@router.post("/{workspace_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def handle_delete_workspace(workspace_id: str, db: DbSession) -> None:
    try:
        await delete_workspace(db, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Workspace '{workspace_id}' not found.") from None
