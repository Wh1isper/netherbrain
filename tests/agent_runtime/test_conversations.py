"""Integration tests for conversation read-only endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Conversation


@pytest.mark.integration
async def test_conversation_list_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/conversations/list")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
async def test_conversation_get_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/conversations/nonexistent/get")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_conversation_list_and_get(client: AsyncClient, db_session: AsyncSession) -> None:
    # Insert test data directly (conversations are created by the session system).
    conv = Conversation(
        conversation_id="conv-1",
        title="Test Conversation",
        metadata_={"source": "discord", "channel": "general"},
        status="active",
    )
    db_session.add(conv)
    await db_session.flush()

    # List
    resp = await client.get("/api/conversations/list")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["conversation_id"] == "conv-1"
    assert data[0]["metadata"] == {"source": "discord", "channel": "general"}

    # Get
    resp = await client.get("/api/conversations/conv-1/get")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test Conversation"


@pytest.mark.integration
async def test_conversation_filter_by_status(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(Conversation(conversation_id="c-active", status="active"))
    db_session.add(Conversation(conversation_id="c-archived", status="archived"))
    await db_session.flush()

    resp = await client.get("/api/conversations/list", params={"status": "active"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["conversation_id"] == "c-active"


@pytest.mark.integration
async def test_conversation_filter_by_metadata(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(Conversation(conversation_id="c-discord", metadata_={"source": "discord"}))
    db_session.add(Conversation(conversation_id="c-telegram", metadata_={"source": "telegram"}))
    await db_session.flush()

    resp = await client.get(
        "/api/conversations/list",
        params={"metadata_contains": '{"source": "discord"}'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["conversation_id"] == "c-discord"
