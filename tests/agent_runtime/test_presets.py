"""Integration tests for preset CRUD endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

PRESET_PAYLOAD = {
    "name": "Test Preset",
    "model": {"name": "anthropic:claude-sonnet-4"},
    "system_prompt": "You are a test assistant.",
}


@pytest.mark.integration
async def test_create_preset(client: AsyncClient) -> None:
    resp = await client.post("/api/presets/create", json=PRESET_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Preset"
    assert data["preset_id"]  # auto-generated UUID
    assert data["model"]["name"] == "anthropic:claude-sonnet-4"
    assert data["is_default"] is False
    assert data["toolsets"] == []
    assert "created_at" in data


@pytest.mark.integration
async def test_create_preset_explicit_id(client: AsyncClient) -> None:
    payload = {**PRESET_PAYLOAD, "preset_id": "my-preset"}
    resp = await client.post("/api/presets/create", json=payload)
    assert resp.status_code == 201
    assert resp.json()["preset_id"] == "my-preset"


@pytest.mark.integration
async def test_create_preset_duplicate(client: AsyncClient) -> None:
    payload = {**PRESET_PAYLOAD, "preset_id": "dup"}
    resp1 = await client.post("/api/presets/create", json=payload)
    assert resp1.status_code == 201
    resp2 = await client.post("/api/presets/create", json=payload)
    assert resp2.status_code == 409


@pytest.mark.integration
async def test_list_presets(client: AsyncClient) -> None:
    await client.post("/api/presets/create", json={**PRESET_PAYLOAD, "name": "P1"})
    await client.post("/api/presets/create", json={**PRESET_PAYLOAD, "name": "P2"})

    resp = await client.get("/api/presets/list")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {d["name"] for d in data} == {"P1", "P2"}


@pytest.mark.integration
async def test_get_preset(client: AsyncClient) -> None:
    await client.post("/api/presets/create", json={**PRESET_PAYLOAD, "preset_id": "get-me"})

    resp = await client.get("/api/presets/get-me/get")
    assert resp.status_code == 200
    assert resp.json()["preset_id"] == "get-me"


@pytest.mark.integration
async def test_get_preset_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/presets/nonexistent/get")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_update_preset_partial(client: AsyncClient) -> None:
    await client.post("/api/presets/create", json={**PRESET_PAYLOAD, "preset_id": "upd"})

    resp = await client.post("/api/presets/upd/update", json={"name": "Updated"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated"
    assert data["system_prompt"] == "You are a test assistant."  # unchanged


@pytest.mark.integration
async def test_update_preset_is_default_unsets_others(client: AsyncClient) -> None:
    await client.post("/api/presets/create", json={**PRESET_PAYLOAD, "preset_id": "p1", "is_default": True})
    await client.post("/api/presets/create", json={**PRESET_PAYLOAD, "preset_id": "p2"})

    # Set p2 as default -- p1 should be unset.
    resp = await client.post("/api/presets/p2/update", json={"is_default": True})
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True

    p1 = await client.get("/api/presets/p1/get")
    assert p1.json()["is_default"] is False


@pytest.mark.integration
async def test_delete_preset(client: AsyncClient) -> None:
    await client.post("/api/presets/create", json={**PRESET_PAYLOAD, "preset_id": "del-me"})

    resp = await client.post("/api/presets/del-me/delete")
    assert resp.status_code == 204

    get_resp = await client.get("/api/presets/del-me/get")
    assert get_resp.status_code == 404


@pytest.mark.integration
async def test_delete_preset_not_found(client: AsyncClient) -> None:
    resp = await client.post("/api/presets/nonexistent/delete")
    assert resp.status_code == 404
