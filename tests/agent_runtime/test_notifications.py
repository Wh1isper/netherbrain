"""Tests for the notification system (events, publish, WebSocket handler)."""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest

from netherbrain.agent_runtime.notifications import (
    ConversationUpdated,
    MailboxUpdated,
    SessionCompleted,
    SessionFailed,
    SessionStarted,
)
from netherbrain.agent_runtime.notifications.publish import CHANNEL, publish_notification

# ---------------------------------------------------------------------------
# Event serialization
# ---------------------------------------------------------------------------


def test_session_started_fields() -> None:
    event = SessionStarted(
        conversation_id="C1",
        session_id="S1",
        session_type="agent",
        transport="sse",
    )
    assert event.type == "session_started"
    assert event.conversation_id == "C1"
    assert event.session_id == "S1"
    assert event.timestamp  # non-empty


def test_session_completed_fields() -> None:
    event = SessionCompleted(
        conversation_id="C1",
        session_id="S1",
        session_type="agent",
        final_message_preview="Hello...",
    )
    assert event.type == "session_completed"
    assert event.final_message_preview == "Hello..."


def test_session_failed_fields() -> None:
    event = SessionFailed(
        conversation_id="C1",
        session_id="S1",
        session_type="async_subagent",
        error="Model error",
    )
    assert event.type == "session_failed"
    assert event.error == "Model error"


def test_mailbox_updated_fields() -> None:
    event = MailboxUpdated(
        conversation_id="C1",
        message_id="M1",
        source_session_id="S2",
        source_type="subagent_result",
        subagent_name="researcher",
        pending_count=3,
    )
    assert event.type == "mailbox_updated"
    assert event.pending_count == 3


def test_conversation_updated_fields() -> None:
    event = ConversationUpdated(
        conversation_id="C1",
        changes=["title", "status"],
    )
    assert event.type == "conversation_updated"
    assert event.changes == ["title", "status"]


def test_event_serializes_to_json() -> None:
    event = SessionStarted(
        conversation_id="C1",
        session_id="S1",
        session_type="agent",
        transport="sse",
    )
    payload = json.dumps(asdict(event))
    parsed = json.loads(payload)
    assert parsed["type"] == "session_started"
    assert parsed["conversation_id"] == "C1"
    assert "timestamp" in parsed


# ---------------------------------------------------------------------------
# publish_notification
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_publish_notification_calls_redis() -> None:
    redis = AsyncMock()
    event = SessionStarted(
        conversation_id="C1",
        session_id="S1",
        session_type="agent",
        transport="sse",
    )

    await publish_notification(redis, event)

    redis.publish.assert_called_once()
    call_args = redis.publish.call_args
    assert call_args[0][0] == CHANNEL
    payload = json.loads(call_args[0][1])
    assert payload["type"] == "session_started"
    assert payload["session_id"] == "S1"


@pytest.mark.anyio
async def test_publish_notification_noop_when_redis_none() -> None:
    # Should not raise
    await publish_notification(
        None,
        SessionStarted(
            conversation_id="C1",
            session_id="S1",
            session_type="agent",
            transport="sse",
        ),
    )


@pytest.mark.anyio
async def test_publish_notification_swallows_redis_errors() -> None:
    redis = AsyncMock()
    redis.publish.side_effect = ConnectionError("Redis down")

    # Should not raise
    await publish_notification(
        redis,
        SessionStarted(
            conversation_id="C1",
            session_id="S1",
            session_type="agent",
            transport="sse",
        ),
    )


# ---------------------------------------------------------------------------
# WebSocket handler (integration with real Redis)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.anyio
async def test_notifications_pubsub_roundtrip(redis_client) -> None:
    """Verify that publish_notification delivers to a Redis Pub/Sub subscriber."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL)

    # Consume the subscribe confirmation message.
    msg = await pubsub.get_message(timeout=2.0)
    assert msg is not None and msg["type"] == "subscribe"

    # Publish a notification.
    event = SessionCompleted(
        conversation_id="C1",
        session_id="S5",
        session_type="agent",
        final_message_preview="Done!",
    )
    await publish_notification(redis_client, event)

    # Read the notification from the subscriber.
    msg = await pubsub.get_message(timeout=2.0)
    assert msg is not None
    assert msg["type"] == "message"

    data = json.loads(msg["data"])
    assert data["type"] == "session_completed"
    assert data["session_id"] == "S5"
    assert data["final_message_preview"] == "Done!"

    await pubsub.unsubscribe(CHANNEL)
    await pubsub.aclose()
