"""Workspace data model.

A workspace is a named, reusable grouping of project references stored in
PostgreSQL -- analogous to a VS Code .code-workspace file.

See spec/agent_runtime/02-configuration.md.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WorkspaceIndex(BaseModel):
    """Workspace row (PG)."""

    workspace_id: str
    name: str | None = None
    projects: list[str] = Field(default_factory=list, description="Ordered project_ids, first = default")
    metadata: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
