"""Tests for the enhanced health endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_health_no_auth_required(client: AsyncClient) -> None:
    """Health endpoint should work even without Authorization header."""
    # Build a request without the default auth header.
    resp = await client.request("GET", "/api/health", headers={})
    assert resp.status_code == 200


@pytest.mark.integration
async def test_health_reports_infrastructure_status(client: AsyncClient) -> None:
    """Health response includes postgres and redis status fields."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()

    assert "status" in data
    assert "postgres" in data
    assert "redis" in data

    # In test fixture: db_engine is None, redis is None.
    assert data["postgres"] == "unavailable"
    assert data["redis"] == "unavailable"
    assert data["status"] == "ok"  # unavailable != error
