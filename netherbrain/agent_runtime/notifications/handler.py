"""WebSocket notification handler.

Maintains two concurrent tasks per connection:
- Reader: receives client frames (ping -> pong).
- Writer: reads from Redis Pub/Sub and forwards to WebSocket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from netherbrain.agent_runtime.notifications.publish import CHANNEL


async def handle_notifications(websocket: WebSocket, redis: aioredis.Redis) -> None:
    """Handle a notification WebSocket connection.

    Subscribes to the Redis Pub/Sub notification channel and forwards
    all messages to the WebSocket client.  Runs until the client
    disconnects or the server shuts down.
    """
    await websocket.accept()

    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(CHANNEL)
        logger.debug("Notification WS: subscribed to {}", CHANNEL)

        reader_task = asyncio.create_task(_reader_loop(websocket), name="notif-reader")
        writer_task = asyncio.create_task(_writer_loop(websocket, pubsub), name="notif-writer")

        # Wait until either task finishes (client disconnect or error).
        done, pending = await asyncio.wait(
            {reader_task, writer_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Propagate exceptions from completed tasks (for logging).
        for task in done:
            if task.exception() is not None:
                logger.debug("Notification WS task {} failed: {}", task.get_name(), task.exception())

    except WebSocketDisconnect:
        logger.debug("Notification WS: client disconnected")
    except Exception:
        logger.exception("Notification WS: unexpected error")
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.aclose()
        logger.debug("Notification WS: cleaned up")


async def _reader_loop(websocket: WebSocket) -> None:
    """Read client frames and respond to ping."""
    while True:
        raw = await websocket.receive_text()
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await _send_error(websocket, "Invalid JSON frame")
            continue

        msg_type = msg.get("type")
        if msg_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong", "timestamp": datetime.now(UTC).isoformat()}))
        elif msg_type is not None:
            logger.debug("Notification WS: ignoring unknown command type '{}'", msg_type)
        else:
            await _send_error(websocket, "Missing 'type' field")


async def _writer_loop(websocket: WebSocket, pubsub: Any) -> None:
    """Read from Redis Pub/Sub and forward to WebSocket."""
    while True:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if message is None:
            continue
        if message["type"] != "message":
            continue

        data = message["data"]
        if isinstance(data, bytes):
            data = data.decode("utf-8")

        try:
            await websocket.send_text(data)
        except Exception:
            # Client likely disconnected; exit the loop.
            return


async def _send_error(websocket: WebSocket, message: str) -> None:
    """Send a non-fatal error frame."""
    await websocket.send_text(
        json.dumps({
            "type": "error",
            "message": message,
            "timestamp": datetime.now(UTC).isoformat(),
        })
    )
