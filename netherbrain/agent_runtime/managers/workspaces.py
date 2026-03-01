"""Workspace CRUD operations.

Encapsulates all workspace data access: create, list, get, update, delete.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Workspace
from netherbrain.agent_runtime.models.api import WorkspaceCreate, WorkspaceUpdate


class DuplicateWorkspaceError(ValueError):
    """Raised when a workspace with the given ID already exists."""


class WorkspaceNotFoundError(LookupError):
    """Raised when a workspace is not found."""


async def create_workspace(db: AsyncSession, body: WorkspaceCreate) -> Workspace:
    """Create a new workspace.  Raises ``DuplicateWorkspaceError`` if ID exists."""
    workspace_id = body.workspace_id or str(uuid.uuid4())

    existing = await db.get(Workspace, workspace_id)
    if existing is not None:
        raise DuplicateWorkspaceError(workspace_id)

    workspace = Workspace(
        workspace_id=workspace_id,
        name=body.name,
        projects=body.projects,
        metadata_=body.metadata,
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


async def list_workspaces(
    db: AsyncSession,
    *,
    metadata_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Workspace]:
    """List workspaces with optional metadata filter, newest first.

    Raises ``ValueError`` if ``metadata_contains`` is not valid JSON.
    """
    stmt = select(Workspace).order_by(Workspace.created_at.desc())

    if metadata_contains is not None:
        try:
            filter_obj = json.loads(metadata_contains)
        except json.JSONDecodeError as exc:
            msg = f"Invalid JSON in metadata_contains: {exc}"
            raise ValueError(msg) from None
        metadata_col = Workspace.__table__.c.metadata
        stmt = stmt.where(metadata_col.cast(PG_JSONB).contains(filter_obj))

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_workspace(db: AsyncSession, workspace_id: str) -> Workspace:
    """Get a workspace by ID.  Raises ``WorkspaceNotFoundError`` if missing."""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise WorkspaceNotFoundError(workspace_id)
    return workspace


async def update_workspace(db: AsyncSession, workspace_id: str, body: WorkspaceUpdate) -> Workspace:
    """Partially update a workspace.  Raises ``WorkspaceNotFoundError`` if missing."""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise WorkspaceNotFoundError(workspace_id)

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return workspace

    # Map 'metadata' field to ORM attribute 'metadata_'.
    if "metadata" in changes:
        changes["metadata_"] = changes.pop("metadata")

    for key, value in changes.items():
        setattr(workspace, key, value)

    await db.commit()
    await db.refresh(workspace)
    return workspace


async def delete_workspace(db: AsyncSession, workspace_id: str) -> None:
    """Delete a workspace.  Raises ``WorkspaceNotFoundError`` if missing."""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise WorkspaceNotFoundError(workspace_id)
    await db.delete(workspace)
    await db.commit()
