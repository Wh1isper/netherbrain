"""Workspace data model.

A workspace is a named, reusable grouping of project references stored in
PostgreSQL -- analogous to a VS Code .code-workspace file.

See spec/agent_runtime/02-configuration.md.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectRef(BaseModel):
    """A reference to a project directory with optional description.

    The ``id`` maps to ``{DATA_ROOT}/{DATA_PREFIX}/projects/{id}/``.
    The optional ``description`` is injected into the agent's environment
    context via an ``InstructableResource``.
    """

    id: str = Field(description="Project identifier (storage mapping key)")
    description: str | None = Field(default=None, description="Human-readable project description")


class WorkspaceIndex(BaseModel):
    """Workspace row (PG)."""

    workspace_id: str
    name: str | None = None
    projects: list[ProjectRef] = Field(default_factory=list, description="Ordered project refs, first = default")
    metadata: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
