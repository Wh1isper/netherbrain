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


@pytest.fixture
def prefixed_store(tmp_path) -> LocalStateStore:
    return LocalStateStore(tmp_path, prefix="alice")


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


async def test_read_state_not_found(store: LocalStateStore) -> None:
    with pytest.raises(FileNotFoundError):
        await store.read_state("nonexistent")


async def test_exists(store: LocalStateStore) -> None:
    assert await store.exists("sess-1") is False

    state = SessionState()
    await store.write_state("sess-1", state)
    assert await store.exists("sess-1") is True


async def test_delete(store: LocalStateStore) -> None:
    state = SessionState()
    await store.write_state("sess-1", state)

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


async def test_prefix_creates_namespaced_path(tmp_path) -> None:
    """Prefix inserts a namespace directory between data_root and sessions."""
    store = LocalStateStore(tmp_path, prefix="alice")
    state = SessionState(context_state={"ns": "alice"})
    await store.write_state("sess-1", state)

    # File should be at {tmp_path}/alice/sessions/sess-1/state.json
    expected = tmp_path / "alice" / "sessions" / "sess-1" / "state.json"
    assert expected.exists()

    result = await store.read_state("sess-1")
    assert result.context_state == {"ns": "alice"}


async def test_prefix_none_no_extra_directory(tmp_path) -> None:
    """No prefix means no extra directory segment."""
    store = LocalStateStore(tmp_path, prefix=None)
    state = SessionState()
    await store.write_state("sess-1", state)

    # File should be at {tmp_path}/sessions/sess-1/state.json
    expected = tmp_path / "sessions" / "sess-1" / "state.json"
    assert expected.exists()


async def test_different_prefixes_isolated(tmp_path) -> None:
    """Different prefixes are fully isolated from each other."""
    store_a = LocalStateStore(tmp_path, prefix="alice")
    store_b = LocalStateStore(tmp_path, prefix="bob")

    await store_a.write_state("sess-1", SessionState(context_state={"user": "alice"}))
    await store_b.write_state("sess-1", SessionState(context_state={"user": "bob"}))

    a = await store_a.read_state("sess-1")
    b = await store_b.read_state("sess-1")
    assert a.context_state == {"user": "alice"}
    assert b.context_state == {"user": "bob"}

    await store_a.delete("sess-1")
    assert await store_a.exists("sess-1") is False
    assert await store_b.exists("sess-1") is True


async def test_prefixed_store_roundtrip(prefixed_store: LocalStateStore) -> None:
    """Prefixed store should work identically to unprefixed for CRUD ops."""
    state = SessionState(
        context_state={"key": "value"},
        message_history=[{"role": "user", "content": "hello"}],
    )
    await prefixed_store.write_state("sess-1", state)
    assert await prefixed_store.exists("sess-1") is True

    result = await prefixed_store.read_state("sess-1")
    assert result.context_state == {"key": "value"}

    await prefixed_store.delete("sess-1")
    assert await prefixed_store.exists("sess-1") is False


# -- Display messages tests ---------------------------------------------------


async def test_write_and_read_display_messages(store: LocalStateStore) -> None:
    """Display messages round-trip as JSON list."""
    messages = [
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m1", "role": "assistant", "delta": "Hello"},
        {"type": "TOOL_CALL_CHUNK", "toolCallId": "tc1", "toolCallName": "search", "delta": '{"q":"test"}'},
    ]
    await store.write_display_messages("sess-1", messages)

    result = await store.read_display_messages("sess-1")
    assert result is not None
    assert len(result) == 2
    assert result[0]["type"] == "TEXT_MESSAGE_CHUNK"
    assert result[0]["delta"] == "Hello"
    assert result[1]["toolCallName"] == "search"


async def test_read_display_messages_not_found(store: LocalStateStore) -> None:
    """Reading display messages for a session with no file returns None."""
    result = await store.read_display_messages("nonexistent")
    assert result is None


async def test_read_display_messages_state_only(store: LocalStateStore) -> None:
    """Session with state.json but no display_messages.json returns None."""
    state = SessionState()
    await store.write_state("sess-1", state)

    result = await store.read_display_messages("sess-1")
    assert result is None


async def test_display_messages_file_path(tmp_path) -> None:
    """Display messages are stored as display_messages.json next to state.json."""
    store = LocalStateStore(tmp_path)
    messages = [{"type": "TEXT_MESSAGE_CHUNK", "delta": "hi"}]
    await store.write_display_messages("sess-1", messages)

    expected = tmp_path / "sessions" / "sess-1" / "display_messages.json"
    assert expected.exists()


async def test_delete_removes_display_messages(store: LocalStateStore) -> None:
    """Delete should remove both state.json and display_messages.json."""
    state = SessionState()
    await store.write_state("sess-1", state)
    await store.write_display_messages("sess-1", [{"type": "TEXT_MESSAGE_CHUNK"}])

    await store.delete("sess-1")
    assert await store.exists("sess-1") is False
    assert await store.read_display_messages("sess-1") is None


async def test_display_messages_with_prefix(tmp_path) -> None:
    """Prefixed store should store display_messages in the right namespace."""
    store = LocalStateStore(tmp_path, prefix="alice")
    messages = [{"type": "TEXT_MESSAGE_CHUNK", "delta": "test"}]
    await store.write_display_messages("sess-1", messages)

    expected = tmp_path / "alice" / "sessions" / "sess-1" / "display_messages.json"
    assert expected.exists()

    result = await store.read_display_messages("sess-1")
    assert result == messages
