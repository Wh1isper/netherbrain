"""Integration tests for S3StateStore against real S3 endpoint.

These tests are marked with @pytest.mark.s3 and require S3 configuration
via NETHER_S3_* environment variables. They use a unique test prefix to
avoid collisions and clean up after themselves.

Required env vars:
    NETHER_S3_ENDPOINT
    NETHER_S3_BUCKET
    NETHER_S3_ACCESS_KEY
    NETHER_S3_SECRET_KEY
"""

from __future__ import annotations

import os
import uuid

import pytest

from netherbrain.agent_runtime.models.session import SessionState
from netherbrain.agent_runtime.store.s3 import S3StateStore

pytestmark = pytest.mark.s3

# -- Read S3 configuration from environment -----------------------------------
_S3_ENDPOINT = os.environ.get("NETHER_S3_ENDPOINT")
_S3_BUCKET = os.environ.get("NETHER_S3_BUCKET")
_S3_ACCESS_KEY = os.environ.get("NETHER_S3_ACCESS_KEY")
_S3_SECRET_KEY = os.environ.get("NETHER_S3_SECRET_KEY")

_s3_configured = all([_S3_ENDPOINT, _S3_BUCKET, _S3_ACCESS_KEY, _S3_SECRET_KEY])
_skip_reason = "S3 tests require NETHER_S3_ENDPOINT, NETHER_S3_BUCKET, NETHER_S3_ACCESS_KEY, NETHER_S3_SECRET_KEY"

pytestmark = [pytest.mark.s3, pytest.mark.skipif(not _s3_configured, reason=_skip_reason)]


@pytest.fixture
def s3_store() -> S3StateStore:
    """S3 store with a unique test prefix to isolate test data."""
    assert _S3_ENDPOINT and _S3_BUCKET and _S3_ACCESS_KEY and _S3_SECRET_KEY
    test_prefix = f"test-{uuid.uuid4().hex[:8]}"
    return S3StateStore(
        bucket=_S3_BUCKET,
        endpoint_url=_S3_ENDPOINT,
        access_key=_S3_ACCESS_KEY,
        secret_key=_S3_SECRET_KEY,
        prefix=test_prefix,
    )


async def test_write_and_read_state(s3_store: S3StateStore) -> None:
    state = SessionState(
        context_state={"key": "value"},
        message_history=[{"role": "user", "content": "hello"}],
        environment_state={"cwd": "/home/user/project"},
    )
    try:
        await s3_store.write_state("sess-1", state)

        result = await s3_store.read_state("sess-1")
        assert result.context_state == {"key": "value"}
        assert result.message_history == [{"role": "user", "content": "hello"}]
        assert result.environment_state == {"cwd": "/home/user/project"}
    finally:
        await s3_store.delete("sess-1")


async def test_read_state_not_found(s3_store: S3StateStore) -> None:
    with pytest.raises(FileNotFoundError):
        await s3_store.read_state("nonexistent")


async def test_exists(s3_store: S3StateStore) -> None:
    assert await s3_store.exists("sess-1") is False

    state = SessionState()
    try:
        await s3_store.write_state("sess-1", state)
        assert await s3_store.exists("sess-1") is True
    finally:
        await s3_store.delete("sess-1")


async def test_delete(s3_store: S3StateStore) -> None:
    state = SessionState()
    await s3_store.write_state("sess-1", state)

    await s3_store.delete("sess-1")
    assert await s3_store.exists("sess-1") is False

    # Delete non-existent is a no-op.
    await s3_store.delete("nonexistent")


async def test_empty_state_roundtrip(s3_store: S3StateStore) -> None:
    """Empty SessionState should round-trip cleanly."""
    state = SessionState()
    try:
        await s3_store.write_state("sess-1", state)

        result = await s3_store.read_state("sess-1")
        assert result.context_state == {}
        assert result.message_history == []
        assert result.environment_state == {}
    finally:
        await s3_store.delete("sess-1")


async def test_multiple_sessions_isolated(s3_store: S3StateStore) -> None:
    """Each session has its own key; no cross-contamination."""
    try:
        await s3_store.write_state("a", SessionState(context_state={"id": "a"}))
        await s3_store.write_state("b", SessionState(context_state={"id": "b"}))

        a = await s3_store.read_state("a")
        b = await s3_store.read_state("b")
        assert a.context_state == {"id": "a"}
        assert b.context_state == {"id": "b"}

        await s3_store.delete("a")
        assert await s3_store.exists("a") is False
        assert await s3_store.exists("b") is True
    finally:
        await s3_store.delete("a")
        await s3_store.delete("b")
