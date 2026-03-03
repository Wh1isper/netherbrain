"""Tests for GET /api/toolsets capability discovery endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from netherbrain.agent_runtime.execution.runtime import _CORE_TOOLSETS, TOOLSET_REGISTRY


@pytest.mark.integration
async def test_list_toolsets_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/toolsets")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.integration
async def test_list_toolsets_schema(client: AsyncClient) -> None:
    """Each item has required fields with correct types."""
    resp = await client.get("/api/toolsets")
    assert resp.status_code == 200
    for item in resp.json():
        assert isinstance(item["name"], str)
        assert isinstance(item["description"], str)
        assert isinstance(item["tools"], list)
        assert isinstance(item["is_alias"], bool)
        assert all(isinstance(t, str) for t in item["tools"])


@pytest.mark.integration
async def test_list_toolsets_contains_registry_entries(client: AsyncClient) -> None:
    """Every key in TOOLSET_REGISTRY is represented in the response."""
    resp = await client.get("/api/toolsets")
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    for ts_name in TOOLSET_REGISTRY:
        assert ts_name in names, f"Toolset '{ts_name}' missing from /api/toolsets response"


@pytest.mark.integration
async def test_list_toolsets_core_alias(client: AsyncClient) -> None:
    """'core' entry is present, marked as alias, and contains all core tools."""
    resp = await client.get("/api/toolsets")
    assert resp.status_code == 200

    core = next((item for item in resp.json() if item["name"] == "core"), None)
    assert core is not None, "core alias missing from response"
    assert core["is_alias"] is True

    # Every tool from every core toolset should appear in core.tools.
    expected_tools: set[str] = set()
    for ts_name in _CORE_TOOLSETS:
        tools = TOOLSET_REGISTRY.get(ts_name, [])
        expected_tools.update(t.name for t in tools)

    core_tools = set(core["tools"])
    assert expected_tools == core_tools


@pytest.mark.integration
async def test_list_toolsets_non_alias_entries_have_tools(client: AsyncClient) -> None:
    """Non-alias toolsets each have at least one tool."""
    resp = await client.get("/api/toolsets")
    assert resp.status_code == 200
    for item in resp.json():
        if not item["is_alias"]:
            assert len(item["tools"]) > 0, f"Toolset '{item['name']}' has no tools"


@pytest.mark.integration
async def test_list_toolsets_requires_auth(client: AsyncClient) -> None:
    """Endpoint rejects requests without Authorization header."""
    from httpx import ASGITransport
    from httpx import AsyncClient as RawClient

    from netherbrain.agent_runtime.app import app

    transport = ASGITransport(app=app)
    async with RawClient(transport=transport, base_url="http://test") as unauth:
        resp = await unauth.get("/api/toolsets")
    assert resp.status_code in (401, 403)
