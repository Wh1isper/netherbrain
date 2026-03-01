"""Workspace CRUD endpoints (RPC-style).

All write operations use POST; reads use GET.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from netherbrain.agent_runtime.db.tables import Workspace
from netherbrain.agent_runtime.deps import DbSession
from netherbrain.agent_runtime.models.api import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("/create", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreate, db: DbSession) -> Workspace:
    """Create a new workspace."""
    workspace_id = body.workspace_id or str(uuid.uuid4())

    existing = await db.get(Workspace, workspace_id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Workspace '{workspace_id}' already exists.")

    workspace = Workspace(
        workspace_id=workspace_id,
        name=body.name,
        projects=body.projects,
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.get("/list", response_model=list[WorkspaceResponse])
async def list_workspaces(db: DbSession) -> list[Workspace]:
    """List all workspaces, ordered by creation time (newest first)."""
    result = await db.execute(select(Workspace).order_by(Workspace.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{workspace_id}/get", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str, db: DbSession) -> Workspace:
    """Get a single workspace by ID."""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Workspace '{workspace_id}' not found.")
    return workspace


@router.post("/{workspace_id}/update", response_model=WorkspaceResponse)
async def update_workspace(workspace_id: str, body: WorkspaceUpdate, db: DbSession) -> Workspace:
    """Partially update a workspace."""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Workspace '{workspace_id}' not found.")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return workspace

    for key, value in changes.items():
        setattr(workspace, key, value)

    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.post("/{workspace_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(workspace_id: str, db: DbSession) -> None:
    """Delete a workspace by ID."""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Workspace '{workspace_id}' not found.")
    await db.delete(workspace)
    await db.commit()
