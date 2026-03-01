"""Integration tests for workspace CRUD endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_workspace_full_crud(client: AsyncClient) -> None:
    """Exercise create -> get -> update -> list -> delete in one test."""
    # Create
    resp = await client.post(
        "/api/workspaces/create",
        json={"name": "My Workspace", "projects": ["/proj/a", "/proj/b"]},
    )
    assert resp.status_code == 201
    ws = resp.json()
    ws_id = ws["workspace_id"]
    assert ws["name"] == "My Workspace"
    assert ws["projects"] == ["/proj/a", "/proj/b"]

    # Get
    resp = await client.get(f"/api/workspaces/{ws_id}/get")
    assert resp.status_code == 200
    assert resp.json()["workspace_id"] == ws_id

    # Update (partial -- only projects)
    resp = await client.post(f"/api/workspaces/{ws_id}/update", json={"projects": ["/proj/c"]})
    assert resp.status_code == 200
    assert resp.json()["projects"] == ["/proj/c"]
    assert resp.json()["name"] == "My Workspace"  # unchanged

    # List
    resp = await client.get("/api/workspaces/list")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Delete
    resp = await client.post(f"/api/workspaces/{ws_id}/delete")
    assert resp.status_code == 204

    resp = await client.get(f"/api/workspaces/{ws_id}/get")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_workspace_duplicate(client: AsyncClient) -> None:
    payload = {"workspace_id": "ws-dup", "name": "W"}
    resp1 = await client.post("/api/workspaces/create", json=payload)
    assert resp1.status_code == 201
    resp2 = await client.post("/api/workspaces/create", json=payload)
    assert resp2.status_code == 409
