"""Unit tests for LocalStateStore.

No database or Docker required -- uses a temporary directory.
"""

from __future__ import annotations

import pytest

from netherbrain.agent_runtime.models.session import SessionState
from netherbrain.agent_runtime.store.local import LocalStateStore


@pytest.fixture
def store(tmp_path) -> LocalStateStore:
    return LocalStateStore(tmp_path)


async def test_write_and_read_state(store: LocalStateStore) -> None:
    state = SessionState(
        context_state={"key": "value"},
        message_history=[{"role": "user", "content": "hello"}],
        environment_state={"cwd": "/home/user/project"},
    )
    await store.write_state("sess-1", state)

    result = await store.read_state("sess-1")
    assert result.context_state == {"key": "value"}
    assert result.message_history == [{"role": "user", "content": "hello"}]
    assert result.environment_state == {"cwd": "/home/user/project"}


async def test_write_and_read_display_messages(store: LocalStateStore) -> None:
    messages = [{"role": "assistant", "text": "Hi there"}]
    await store.write_display_messages("sess-1", messages)

    result = await store.read_display_messages("sess-1")
    assert result == messages


async def test_read_state_not_found(store: LocalStateStore) -> None:
    with pytest.raises(FileNotFoundError):
        await store.read_state("nonexistent")


async def test_read_display_messages_not_found(store: LocalStateStore) -> None:
    with pytest.raises(FileNotFoundError):
        await store.read_display_messages("nonexistent")


async def test_exists(store: LocalStateStore) -> None:
    assert await store.exists("sess-1") is False

    state = SessionState()
    await store.write_state("sess-1", state)
    assert await store.exists("sess-1") is True


async def test_delete(store: LocalStateStore) -> None:
    state = SessionState()
    await store.write_state("sess-1", state)
    await store.write_display_messages("sess-1", [{"text": "hi"}])

    await store.delete("sess-1")
    assert await store.exists("sess-1") is False

    # Delete non-existent is a no-op.
    await store.delete("nonexistent")


async def test_empty_state_roundtrip(store: LocalStateStore) -> None:
    """Empty SessionState should round-trip cleanly."""
    state = SessionState()
    await store.write_state("sess-1", state)

    result = await store.read_state("sess-1")
    assert result.context_state == {}
    assert result.message_history == []
    assert result.environment_state == {}


async def test_multiple_sessions_isolated(store: LocalStateStore) -> None:
    """Each session has its own directory; no cross-contamination."""
    await store.write_state("a", SessionState(context_state={"id": "a"}))
    await store.write_state("b", SessionState(context_state={"id": "b"}))

    a = await store.read_state("a")
    b = await store.read_state("b")
    assert a.context_state == {"id": "a"}
    assert b.context_state == {"id": "b"}

    await store.delete("a")
    assert await store.exists("a") is False
    assert await store.exists("b") is True
