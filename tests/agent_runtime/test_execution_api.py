"""Integration tests for conversation and session execution API endpoints.

Tests the HTTP layer (request validation, error translation, response shapes)
with the execution pipeline mocked at the ``launch_session`` boundary.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.context import RuntimeSession
from netherbrain.agent_runtime.db.tables import Conversation, Preset, Session
from netherbrain.agent_runtime.execution.launch import LaunchResult
from netherbrain.agent_runtime.models.enums import Transport
from netherbrain.agent_runtime.registry import SessionRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRESET_DEFAULTS = {
    "model": {"name": "openai:gpt-4o"},
    "system_prompt": "You are a helpful assistant.",
    "toolsets": [],
    "environment": {},
    "tool_config": {},
    "subagents": {},
    "mcp_servers": [],
}


async def _seed_preset(db: AsyncSession, preset_id: str = "test-preset") -> Preset:
    preset = Preset(preset_id=preset_id, name="Test", **_PRESET_DEFAULTS)
    db.add(preset)
    await db.flush()
    return preset


async def _seed_conversation(db: AsyncSession, conv_id: str = "conv-1", status: str = "active") -> Conversation:
    conv = Conversation(conversation_id=conv_id, status=status)
    db.add(conv)
    await db.flush()
    return conv


async def _seed_committed_session(
    db: AsyncSession,
    session_id: str = "sess-1",
    conv_id: str = "conv-1",
    preset_id: str = "test-preset",
) -> Session:
    sess = Session(
        session_id=session_id,
        conversation_id=conv_id,
        status="committed",
        preset_id=preset_id,
        input=[{"type": "text", "text": "hello"}],
        final_message="Hi there!",
    )
    db.add(sess)
    await db.flush()
    return sess


def _make_launch_result(
    session_id: str = "new-sess",
    conversation_id: str = "new-conv",
) -> LaunchResult:
    """Create a LaunchResult with stream transport (returns 202, no SSE hang)."""
    return LaunchResult(
        session_id=session_id,
        conversation_id=conversation_id,
        transport=Transport.STREAM,
        stream_key=f"stream:{session_id}",
    )


def _register_session(
    registry: SessionRegistry,
    session_id: str = "live-sess",
    conversation_id: str = "conv-1",
    transport: Transport = Transport.SSE,
) -> RuntimeSession:
    """Register a fake live session in the registry."""
    streamer = MagicMock()
    streamer.interrupt = MagicMock()
    ctx = RuntimeSession(
        session_id=session_id,
        conversation_id=conversation_id,
        transport=transport,
        streamer=streamer,
        sdk_context=None,
        stream_key=None,
    )
    registry.register(ctx)
    return ctx


# ===========================================================================
# POST /conversations/run
# ===========================================================================


@pytest.mark.integration
async def test_run_no_input(client: AsyncClient, db_session: AsyncSession) -> None:
    """422 when no input is provided."""
    await _seed_preset(db_session)
    resp = await client.post(
        "/api/conversations/run",
        json={"preset_id": "test-preset"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_run_new_conversation_missing_preset(client: AsyncClient) -> None:
    """422 when creating a new conversation without preset_id."""
    resp = await client.post(
        "/api/conversations/run",
        json={"input": [{"type": "text", "text": "hello"}]},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_run_conversation_not_found(client: AsyncClient) -> None:
    """404 when continuing a conversation that doesn't exist."""
    resp = await client.post(
        "/api/conversations/run",
        json={
            "conversation_id": "nonexistent",
            "input": [{"type": "text", "text": "hello"}],
        },
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_run_conversation_busy(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """409 when conversation already has an active session."""
    await _seed_preset(db_session)
    await _seed_conversation(db_session, "conv-busy")
    _register_session(test_registry, session_id="active-s", conversation_id="conv-busy")

    resp = await client.post(
        "/api/conversations/run",
        json={
            "conversation_id": "conv-busy",
            "input": [{"type": "text", "text": "hello"}],
        },
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "conversation_busy"
    assert data["active_session"]["session_id"] == "active-s"


@pytest.mark.integration
@patch("netherbrain.agent_runtime.managers.execution.launch_session", new_callable=AsyncMock)
async def test_run_new_conversation_success(
    mock_launch: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Happy path: new conversation returns 202 with session info."""
    await _seed_preset(db_session)
    mock_launch.return_value = _make_launch_result()

    resp = await client.post(
        "/api/conversations/run",
        json={
            "preset_id": "test-preset",
            "input": [{"type": "text", "text": "hello"}],
            "transport": "stream",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["session_id"] == "new-sess"
    assert data["conversation_id"] == "new-conv"
    assert data["stream_key"] == "stream:new-sess"
    mock_launch.assert_awaited_once()


@pytest.mark.integration
@patch("netherbrain.agent_runtime.managers.execution.launch_session", new_callable=AsyncMock)
async def test_run_with_metadata(
    mock_launch: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Metadata is passed through to the conversation."""
    await _seed_preset(db_session)
    mock_launch.return_value = _make_launch_result()

    resp = await client.post(
        "/api/conversations/run",
        json={
            "preset_id": "test-preset",
            "input": [{"type": "text", "text": "hello"}],
            "transport": "stream",
            "metadata": {"source": "test"},
        },
    )
    assert resp.status_code == 202
    mock_launch.assert_awaited_once()


@pytest.mark.integration
@patch("netherbrain.agent_runtime.managers.execution.launch_session", new_callable=AsyncMock)
async def test_run_continue_conversation_success(
    mock_launch: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Continue an existing conversation (finds parent session)."""
    await _seed_preset(db_session)
    await _seed_conversation(db_session, "conv-cont")
    await _seed_committed_session(db_session, "sess-parent", "conv-cont")
    mock_launch.return_value = _make_launch_result(conversation_id="conv-cont")

    resp = await client.post(
        "/api/conversations/run",
        json={
            "conversation_id": "conv-cont",
            "preset_id": "test-preset",
            "input": [{"type": "text", "text": "follow up"}],
            "transport": "stream",
        },
    )
    assert resp.status_code == 202
    mock_launch.assert_awaited_once()
    # Verify parent_session_id was passed.
    call_kwargs = mock_launch.call_args.kwargs
    assert call_kwargs["parent_session_id"] == "sess-parent"


@pytest.mark.integration
async def test_run_preset_not_found(client: AsyncClient) -> None:
    """404 when preset doesn't exist."""
    resp = await client.post(
        "/api/conversations/run",
        json={
            "preset_id": "nonexistent-preset",
            "input": [{"type": "text", "text": "hello"}],
        },
    )
    assert resp.status_code == 404


# ===========================================================================
# POST /conversations/{id}/fork
# ===========================================================================


@pytest.mark.integration
async def test_fork_conversation_not_found(client: AsyncClient) -> None:
    """404 when source conversation doesn't exist."""
    resp = await client.post(
        "/api/conversations/nonexistent/fork",
        json={"preset_id": "p1"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_fork_no_committed_session(client: AsyncClient, db_session: AsyncSession) -> None:
    """404 when conversation has no committed sessions to fork from."""
    await _seed_preset(db_session)
    await _seed_conversation(db_session, "conv-empty")

    resp = await client.post(
        "/api/conversations/conv-empty/fork",
        json={"preset_id": "test-preset"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
@patch("netherbrain.agent_runtime.managers.execution.launch_session", new_callable=AsyncMock)
async def test_fork_success(
    mock_launch: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Happy path: fork creates a new conversation from latest committed session."""
    await _seed_preset(db_session)
    await _seed_conversation(db_session, "conv-fork")
    await _seed_committed_session(db_session, "sess-fork-parent", "conv-fork")
    mock_launch.return_value = _make_launch_result(conversation_id="forked-conv")

    resp = await client.post(
        "/api/conversations/conv-fork/fork",
        json={"preset_id": "test-preset", "transport": "stream"},
    )
    assert resp.status_code == 202
    mock_launch.assert_awaited_once()
    call_kwargs = mock_launch.call_args.kwargs
    assert call_kwargs["parent_session_id"] == "sess-fork-parent"


@pytest.mark.integration
async def test_fork_session_not_in_conversation(client: AsyncClient, db_session: AsyncSession) -> None:
    """422 when from_session_id doesn't belong to the conversation."""
    await _seed_preset(db_session)
    await _seed_conversation(db_session, "conv-a")
    await _seed_conversation(db_session, "conv-b")
    await _seed_committed_session(db_session, "sess-in-b", "conv-b")

    resp = await client.post(
        "/api/conversations/conv-a/fork",
        json={"preset_id": "test-preset", "from_session_id": "sess-in-b"},
    )
    assert resp.status_code == 422


# ===========================================================================
# POST /conversations/{id}/interrupt
# ===========================================================================


@pytest.mark.integration
async def test_interrupt_conversation_not_found(client: AsyncClient) -> None:
    """404 when conversation doesn't exist."""
    resp = await client.post("/api/conversations/nonexistent/interrupt")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_interrupt_conversation_no_active(client: AsyncClient, db_session: AsyncSession) -> None:
    """Returns interrupted=0 when no active sessions."""
    await _seed_conversation(db_session, "conv-idle")

    resp = await client.post("/api/conversations/conv-idle/interrupt")
    assert resp.status_code == 200
    assert resp.json()["interrupted"] == 0


@pytest.mark.integration
async def test_interrupt_conversation_with_active(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """Interrupts active session and returns count."""
    await _seed_conversation(db_session, "conv-int")
    _register_session(test_registry, session_id="s-int", conversation_id="conv-int")

    resp = await client.post("/api/conversations/conv-int/interrupt")
    assert resp.status_code == 200
    assert resp.json()["interrupted"] == 1


# ===========================================================================
# POST /conversations/{id}/steer
# ===========================================================================


@pytest.mark.integration
async def test_steer_conversation_not_found(client: AsyncClient) -> None:
    """404 when conversation doesn't exist."""
    resp = await client.post(
        "/api/conversations/nonexistent/steer",
        json={"input": [{"type": "text", "text": "hint"}]},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_steer_conversation_no_active_session(client: AsyncClient, db_session: AsyncSession) -> None:
    """404 when no active session to steer."""
    await _seed_conversation(db_session, "conv-nosteer")

    resp = await client.post(
        "/api/conversations/conv-nosteer/steer",
        json={"input": [{"type": "text", "text": "hint"}]},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_steer_conversation_empty_text(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """422 when steering text is empty."""
    await _seed_conversation(db_session, "conv-st")
    _register_session(test_registry, session_id="s-st", conversation_id="conv-st")

    resp = await client.post(
        "/api/conversations/conv-st/steer",
        json={"input": [{"type": "text", "text": ""}]},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_steer_conversation_context_not_ready(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """409 when session SDK context is not yet available."""
    await _seed_conversation(db_session, "conv-ctx")
    # sdk_context=None means context not ready
    _register_session(test_registry, session_id="s-ctx", conversation_id="conv-ctx")

    resp = await client.post(
        "/api/conversations/conv-ctx/steer",
        json={"input": [{"type": "text", "text": "please hurry"}]},
    )
    assert resp.status_code == 409


# ===========================================================================
# POST /sessions/execute
# ===========================================================================


@pytest.mark.integration
async def test_execute_no_input(client: AsyncClient) -> None:
    """422 when no input is provided."""
    resp = await client.post(
        "/api/sessions/execute",
        json={"preset_id": "test-preset"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_execute_preset_not_found(client: AsyncClient) -> None:
    """404 when preset doesn't exist."""
    resp = await client.post(
        "/api/sessions/execute",
        json={
            "preset_id": "nonexistent",
            "input": [{"type": "text", "text": "hello"}],
        },
    )
    assert resp.status_code == 404


@pytest.mark.integration
@patch("netherbrain.agent_runtime.managers.execution.launch_session", new_callable=AsyncMock)
async def test_execute_success(
    mock_launch: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Happy path: direct session execution."""
    await _seed_preset(db_session)
    mock_launch.return_value = _make_launch_result(session_id="exec-s1")

    resp = await client.post(
        "/api/sessions/execute",
        json={
            "preset_id": "test-preset",
            "input": [{"type": "text", "text": "hello"}],
            "transport": "stream",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["session_id"] == "exec-s1"
    mock_launch.assert_awaited_once()


@pytest.mark.integration
@patch("netherbrain.agent_runtime.managers.execution.launch_session", new_callable=AsyncMock)
async def test_execute_with_parent(
    mock_launch: AsyncMock,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Execute with parent_session_id for continuation."""
    await _seed_preset(db_session)
    await _seed_conversation(db_session, "conv-exec")
    await _seed_committed_session(db_session, "parent-exec", "conv-exec")
    mock_launch.return_value = _make_launch_result()

    resp = await client.post(
        "/api/sessions/execute",
        json={
            "preset_id": "test-preset",
            "parent_session_id": "parent-exec",
            "input": [{"type": "text", "text": "continue"}],
            "transport": "stream",
        },
    )
    assert resp.status_code == 202
    call_kwargs = mock_launch.call_args.kwargs
    assert call_kwargs["parent_session_id"] == "parent-exec"


# ===========================================================================
# GET /sessions/{id}/status
# ===========================================================================


@pytest.mark.integration
async def test_session_status_not_found(client: AsyncClient) -> None:
    """404 when session doesn't exist in registry or PG."""
    resp = await client.get("/api/sessions/nonexistent/status")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_session_status_from_pg(client: AsyncClient, db_session: AsyncSession) -> None:
    """Falls back to PG when session is not in registry."""
    await _seed_conversation(db_session, "conv-status")
    sess = Session(
        session_id="sess-done",
        conversation_id="conv-status",
        status="committed",
        transport="sse",
    )
    db_session.add(sess)
    await db_session.flush()

    resp = await client.get("/api/sessions/sess-done/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess-done"
    assert data["status"] == "committed"


@pytest.mark.integration
async def test_session_status_from_registry(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """Returns live status from registry when session is active."""
    _register_session(test_registry, session_id="live-s", conversation_id="conv-x")

    resp = await client.get("/api/sessions/live-s/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "live-s"
    assert data["status"] == "created"


# ===========================================================================
# POST /sessions/{id}/interrupt
# ===========================================================================


@pytest.mark.integration
async def test_interrupt_session_not_found(client: AsyncClient) -> None:
    """404 when session is not active."""
    resp = await client.post("/api/sessions/nonexistent/interrupt")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_interrupt_session_success(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """Interrupts an active session."""
    ctx = _register_session(test_registry, session_id="s-int2", conversation_id="conv-int2")

    resp = await client.post("/api/sessions/s-int2/interrupt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s-int2"
    assert data["interrupted"] is True
    ctx.streamer.interrupt.assert_called_once()


# ===========================================================================
# POST /sessions/{id}/steer
# ===========================================================================


@pytest.mark.integration
async def test_steer_session_not_found(client: AsyncClient) -> None:
    """404 when session is not active."""
    resp = await client.post(
        "/api/sessions/nonexistent/steer",
        json={"input": [{"type": "text", "text": "hint"}]},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_steer_session_empty_text(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """422 when steering text is empty."""
    _register_session(test_registry, session_id="s-steer", conversation_id="conv-steer")

    resp = await client.post(
        "/api/sessions/s-steer/steer",
        json={"input": [{"type": "text", "text": ""}]},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_steer_session_context_not_ready(
    client: AsyncClient,
    db_session: AsyncSession,
    test_registry: SessionRegistry,
) -> None:
    """409 when SDK context not yet available."""
    _register_session(test_registry, session_id="s-steer2", conversation_id="conv-steer2")

    resp = await client.post(
        "/api/sessions/s-steer2/steer",
        json={"input": [{"type": "text", "text": "do something"}]},
    )
    assert resp.status_code == 409


# ===========================================================================
# GET /conversations/{id}/turns (extended)
# ===========================================================================


@pytest.mark.integration
async def test_conversation_turns_not_found(client: AsyncClient) -> None:
    """404 when conversation doesn't exist."""
    resp = await client.get("/api/conversations/nonexistent/turns")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_conversation_turns_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Returns turns from committed sessions."""
    await _seed_conversation(db_session, "conv-turns")
    sess = Session(
        session_id="s-turn1",
        conversation_id="conv-turns",
        status="committed",
        input=[{"type": "text", "text": "question"}],
        final_message="answer",
    )
    db_session.add(sess)
    await db_session.flush()

    resp = await client.get("/api/conversations/conv-turns/turns")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["input"] == [{"type": "text", "text": "question"}]
    assert data[0]["final_message"] == "answer"
