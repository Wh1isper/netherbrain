"""Integration smoke tests for database and Redis fixtures.

Verifies the testcontainers + Alembic migration + savepoint rollback
pipeline works end-to-end.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.db.tables import Preset

pytestmark = pytest.mark.integration


async def test_alembic_migrations_applied(db_session: AsyncSession):
    """All tables from the initial migration should exist."""
    result = await db_session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
    )
    tables = sorted(row[0] for row in result)
    assert "presets" in tables
    assert "workspaces" in tables
    assert "conversations" in tables
    assert "sessions" in tables
    assert "mailbox" in tables


async def test_savepoint_rollback_isolation(db_session: AsyncSession):
    """Rows inserted in a test should not persist to the next test."""
    # Insert a preset
    preset = Preset(
        preset_id="test-preset-1",
        name="Test Preset",
        model={"provider": "openai", "model": "gpt-4"},
        system_prompt="You are a test assistant.",
    )
    db_session.add(preset)
    await db_session.commit()  # commits savepoint, not the real txn

    # Verify it's visible within this test
    result = await db_session.execute(select(Preset).where(Preset.preset_id == "test-preset-1"))
    row = result.scalar_one()
    assert row.name == "Test Preset"


async def test_savepoint_rollback_clean_state(db_session: AsyncSession):
    """Previous test's data should have been rolled back."""
    result = await db_session.execute(select(Preset).where(Preset.preset_id == "test-preset-1"))
    row = result.scalar_one_or_none()
    assert row is None, "Savepoint rollback did not clean up previous test's data"


async def test_redis_connection(redis_client):
    """Redis client should be functional."""
    await redis_client.set("test_key", "test_value")
    value = await redis_client.get("test_key")
    assert value == b"test_value"
