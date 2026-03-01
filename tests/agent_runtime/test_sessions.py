"""Integration tests for SessionManager and session/conversation endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from netherbrain.agent_runtime.managers.sessions import SessionManager
from netherbrain.agent_runtime.models.enums import SessionStatus, SessionType, Transport
from netherbrain.agent_runtime.models.session import RunSummary, SessionState, UsageSummary
from netherbrain.agent_runtime.registry import SessionRegistry
from netherbrain.agent_runtime.store.local import LocalStateStore


@pytest.fixture
def store(tmp_path) -> LocalStateStore:
    return LocalStateStore(tmp_path)


@pytest.fixture
def registry() -> SessionRegistry:
    return SessionRegistry()


@pytest.fixture
def manager(store: LocalStateStore, registry: SessionRegistry) -> SessionManager:
    return SessionManager(store=store, registry=registry)


# ---------------------------------------------------------------------------
# SessionManager unit-integration tests (real DB, real store, no HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_root_session(manager: SessionManager, db_session: AsyncSession) -> None:
    """Root session: conversation_id = session_id, conversation row created."""
    row = await manager.create_session(db_session, preset_id="preset-1")

    assert row.session_id
    assert row.conversation_id == row.session_id  # root
    assert row.parent_session_id is None
    assert row.status == SessionStatus.CREATED
    assert row.session_type == SessionType.AGENT
    assert row.transport == Transport.SSE


@pytest.mark.integration
async def test_create_continuation_session(manager: SessionManager, db_session: AsyncSession) -> None:
    """Continuation: inherits conversation_id from parent."""
    root = await manager.create_session(db_session)
    root_id = root.session_id
    root_conv = root.conversation_id

    child = await manager.create_session(db_session, parent_session_id=root_id)

    assert child.conversation_id == root_conv
    assert child.parent_session_id == root_id


@pytest.mark.integration
async def test_create_fork_session(manager: SessionManager, db_session: AsyncSession) -> None:
    """Fork: new conversation_id, new conversation row."""
    root = await manager.create_session(db_session)
    root_id = root.session_id
    root_conv = root.conversation_id

    forked = await manager.create_session(
        db_session,
        parent_session_id=root_id,
        conversation_id="fork-conv",
    )

    assert forked.conversation_id == "fork-conv"
    assert forked.parent_session_id == root_id
    assert forked.conversation_id != root_conv


@pytest.mark.integration
async def test_create_session_invalid_parent(manager: SessionManager, db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="not found"):
        await manager.create_session(db_session, parent_session_id="nonexistent")


@pytest.mark.integration
async def test_commit_session(manager: SessionManager, store: LocalStateStore, db_session: AsyncSession) -> None:
    """Commit writes state to store and updates PG status."""
    row = await manager.create_session(db_session)
    session_id = row.session_id

    state = SessionState(
        context_state={"agent": "data"},
        message_history=[{"role": "user", "content": "hi"}],
    )
    display = [{"role": "assistant", "text": "hello"}]
    summary = RunSummary(
        duration_ms=1234,
        usage=UsageSummary(total_tokens=100, prompt_tokens=80, completion_tokens=20, model_requests=1),
    )

    committed = await manager.commit_session(
        db_session,
        session_id,
        state=state,
        display_messages=display,
        run_summary=summary,
    )

    assert committed.status == SessionStatus.COMMITTED
    assert committed.run_summary["duration_ms"] == 1234

    # Verify state store.
    stored = await store.read_state(session_id)
    assert stored.context_state == {"agent": "data"}

    stored_display = await store.read_display_messages(session_id)
    assert stored_display == display


@pytest.mark.integration
async def test_fail_session(manager: SessionManager, db_session: AsyncSession) -> None:
    row = await manager.create_session(db_session)
    session_id = row.session_id

    await manager.fail_session(db_session, session_id)

    result = await manager.get_session(db_session, session_id)
    assert result["index"].status == SessionStatus.FAILED


@pytest.mark.integration
async def test_get_session_with_state(manager: SessionManager, db_session: AsyncSession) -> None:
    row = await manager.create_session(db_session)
    session_id = row.session_id

    state = SessionState(context_state={"k": "v"})
    await manager.commit_session(db_session, session_id, state=state)

    result = await manager.get_session(db_session, session_id, include_state=True)
    assert result["state"].context_state == {"k": "v"}


@pytest.mark.integration
async def test_get_session_not_found(manager: SessionManager, db_session: AsyncSession) -> None:
    with pytest.raises(LookupError, match="not found"):
        await manager.get_session(db_session, "nonexistent")


@pytest.mark.integration
async def test_list_sessions(manager: SessionManager, db_session: AsyncSession) -> None:
    root = await manager.create_session(db_session)
    root_id = root.session_id
    root_conv = root.conversation_id

    child = await manager.create_session(db_session, parent_session_id=root_id)
    child_id = child.session_id

    sessions = await manager.list_sessions(db_session, root_conv)
    ids = [s.session_id for s in sessions]
    assert root_id in ids
    assert child_id in ids
    assert len(sessions) == 2


@pytest.mark.integration
async def test_conversation_turns(manager: SessionManager, db_session: AsyncSession) -> None:
    """Turns aggregates display_messages across committed sessions."""
    root = await manager.create_session(db_session)
    root_id = root.session_id
    conv_id = root.conversation_id

    await manager.commit_session(
        db_session,
        root_id,
        state=SessionState(),
        display_messages=[{"role": "user", "text": "q1"}, {"role": "assistant", "text": "a1"}],
    )

    child = await manager.create_session(db_session, parent_session_id=root_id)
    child_id = child.session_id

    await manager.commit_session(
        db_session,
        child_id,
        state=SessionState(),
        display_messages=[{"role": "user", "text": "q2"}, {"role": "assistant", "text": "a2"}],
    )

    turns = await manager.get_conversation_turns(db_session, conv_id)
    assert len(turns) == 4
    assert turns[0]["text"] == "q1"
    assert turns[3]["text"] == "a2"


@pytest.mark.integration
async def test_recover_orphaned_sessions(manager: SessionManager, db_session: AsyncSession) -> None:
    """Startup recovery marks status=created sessions as failed."""
    s1 = await manager.create_session(db_session)
    s1_id = s1.session_id

    s2 = await manager.create_session(db_session)
    s2_id = s2.session_id

    # Commit s2 so only s1 remains orphaned.
    await manager.commit_session(db_session, s2_id, state=SessionState())

    recovered = await SessionManager.recover_orphaned_sessions(db_session)
    assert recovered == 1

    result = await manager.get_session(db_session, s1_id)
    assert result["index"].status == SessionStatus.FAILED


# ---------------------------------------------------------------------------
# API endpoint tests (via httpx client)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_conversation_update(client: AsyncClient, db_session: AsyncSession) -> None:
    """POST /conversations/{id}/update modifies conversation fields."""
    from netherbrain.agent_runtime.db.tables import Conversation

    conv = Conversation(conversation_id="conv-upd", status="active")
    db_session.add(conv)
    await db_session.commit()

    resp = await client.post("/api/conversations/conv-upd/update", json={"title": "New Title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "New Title"


@pytest.mark.integration
async def test_conversation_update_not_found(client: AsyncClient) -> None:
    resp = await client.post("/api/conversations/nope/update", json={"title": "x"})
    assert resp.status_code == 404


@pytest.mark.integration
async def test_conversation_sessions_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """GET /conversations/{id}/sessions lists sessions."""
    from netherbrain.agent_runtime.db.tables import Conversation, Session

    conv = Conversation(conversation_id="conv-sess", status="active")
    db_session.add(conv)
    s1 = Session(session_id="s1", conversation_id="conv-sess", status="committed")
    s2 = Session(session_id="s2", conversation_id="conv-sess", status="created", parent_session_id="s1")
    db_session.add_all([s1, s2])
    await db_session.commit()

    resp = await client.get("/api/conversations/conv-sess/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


@pytest.mark.integration
async def test_session_get_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """GET /sessions/{id}/get returns session detail."""
    from netherbrain.agent_runtime.db.tables import Conversation, Session

    conv = Conversation(conversation_id="conv-sg", status="active")
    db_session.add(conv)
    sess = Session(session_id="sg-1", conversation_id="conv-sg", status="committed")
    db_session.add(sess)
    await db_session.commit()

    resp = await client.get("/api/sessions/sg-1/get")
    assert resp.status_code == 200
    data = resp.json()
    assert data["index"]["session_id"] == "sg-1"
    assert data["state"] is None  # not requested


@pytest.mark.integration
async def test_session_get_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/sessions/nonexistent/get")
    assert resp.status_code == 404
