"""Interactive shell WebSocket endpoint.

Thin WebSocket adapter -- delegates PTY lifecycle to the shell manager.
Authentication is handled by the existing ``BearerAuthMiddleware`` which
supports ``?token=`` query parameter for WebSocket connections.

Protocol:
- Binary frames: raw PTY I/O (keystrokes in, terminal output out)
- Text frames (JSON): control messages (resize, exit)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from loguru import logger

from netherbrain.agent_runtime.auth import AuthContext
from netherbrain.agent_runtime.managers.files import ProjectPathResolver
from netherbrain.agent_runtime.managers.shell import PtyProcess, ShellLimitError, ShellRegistry
from netherbrain.agent_runtime.settings import get_settings

router = APIRouter(prefix="/shell", tags=["shell"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolver() -> ProjectPathResolver:
    """Create a path resolver from current settings."""
    s = get_settings()
    return ProjectPathResolver(data_root=s.data_root, data_prefix=s.data_prefix)


def _get_auth(websocket: WebSocket) -> AuthContext | None:
    """Extract auth context set by BearerAuthMiddleware on the WebSocket scope."""
    return getattr(websocket.state, "auth", None)


def _get_shell_registry(websocket: WebSocket) -> ShellRegistry:
    """Get the ShellRegistry from app state."""
    return websocket.app.state.shell_registry


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/{project_id}/connect")
async def shell_connect(websocket: WebSocket, project_id: str) -> None:
    """Open an interactive shell session in the project directory.

    Query parameters:
    - ``token``: Auth token (required, handled by middleware).
    - ``cols``: Initial terminal columns (default: 80).
    - ``rows``: Initial terminal rows (default: 24).
    """
    # -- Auth ------------------------------------------------------------------
    auth = _get_auth(websocket)
    if auth is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
        return

    # -- Resolve project path --------------------------------------------------
    resolver = _resolver()
    try:
        project_root = resolver.project_root(project_id)
    except LookupError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=f"Project '{project_id}' not found")
        return

    # -- Parse initial size from query params ----------------------------------
    cols = int(websocket.query_params.get("cols", "80"))
    rows = int(websocket.query_params.get("rows", "24"))

    # -- Accept the WebSocket connection ---------------------------------------
    await websocket.accept()

    # -- Spawn PTY and register ------------------------------------------------
    shell_id = f"shell-{uuid.uuid4().hex[:12]}"
    registry = _get_shell_registry(websocket)

    try:
        pty = PtyProcess.spawn(
            cwd=project_root,
            cols=cols,
            rows=rows,
            shell_id=shell_id,
        )
    except OSError as exc:
        logger.error("Failed to spawn PTY for project {}: {}", project_id, exc)
        await _send_exit(websocket, -1, error=str(exc))
        await websocket.close()
        return

    try:
        registry.register(pty)
    except ShellLimitError as exc:
        logger.warning("Shell limit reached: {}", exc)
        await pty.close()
        await _send_exit(websocket, -1, error=str(exc))
        await websocket.close()
        return

    logger.info(
        "Shell opened: shell_id={}, project={}, user={}, pid={}",
        shell_id,
        project_id,
        auth.user_id,
        pty.pid,
    )

    # -- Bidirectional I/O loop ------------------------------------------------
    try:
        async with pty:
            await _io_loop(websocket, pty)
    except WebSocketDisconnect:
        logger.debug("Shell WebSocket disconnected: shell_id={}", shell_id)
    except Exception:
        logger.exception("Shell error: shell_id={}", shell_id)
    finally:
        # Ensure PTY is closed (idempotent).
        exit_code = await pty.close()
        registry.unregister(shell_id)
        logger.info("Shell closed: shell_id={}, exit_code={}", shell_id, exit_code)


async def _io_loop(websocket: WebSocket, pty: PtyProcess) -> None:
    """Run bidirectional I/O between WebSocket and PTY.

    Spawns two concurrent tasks:
    - pty_to_ws: reads from PTY, sends binary frames to WebSocket
    - ws_to_pty: reads from WebSocket, writes to PTY (binary) or handles
      control messages (text/JSON)

    Exits when either side closes.
    """
    pty_to_ws_task = asyncio.create_task(_pty_to_ws(websocket, pty))
    ws_to_pty_task = asyncio.create_task(_ws_to_pty(websocket, pty))

    try:
        # Wait for either task to finish (first one wins).
        done, pending = await asyncio.wait(
            {pty_to_ws_task, ws_to_pty_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Cancel the other task.
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        # Re-raise any exception from the completed task.
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                raise exc
    except WebSocketDisconnect:
        raise
    except asyncio.CancelledError:
        pass


async def _pty_to_ws(websocket: WebSocket, pty: PtyProcess) -> None:
    """Forward PTY output to WebSocket as binary frames."""
    while True:
        data = await pty.read()
        if data is None:
            # PTY process exited.
            exit_code = await pty.close()
            with contextlib.suppress(Exception):
                await _send_exit(websocket, exit_code)
            return
        try:
            await websocket.send_bytes(data)
        except (WebSocketDisconnect, RuntimeError):
            return


async def _ws_to_pty(websocket: WebSocket, pty: PtyProcess) -> None:
    """Forward WebSocket input to PTY.

    Binary frames -> PTY stdin.
    Text frames (JSON) -> control messages (resize).
    """
    while True:
        message = await websocket.receive()
        msg_type = message.get("type", "")

        if msg_type == "websocket.disconnect":
            return

        if message.get("bytes"):
            pty.write(message["bytes"])
        elif message.get("text"):
            await _handle_control_message(message["text"], pty)


async def _handle_control_message(text: str, pty: PtyProcess) -> None:
    """Parse and handle a JSON control message."""
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Shell: invalid JSON control message: {}", text[:200])
        return

    msg_type = msg.get("type")

    if msg_type == "resize":
        cols = msg.get("cols", 80)
        rows = msg.get("rows", 24)
        pty.resize(int(cols), int(rows))
    else:
        logger.debug("Shell: unknown control message type: {}", msg_type)


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------


async def _send_exit(websocket: WebSocket, code: int, *, error: str | None = None) -> None:
    """Send an exit control frame to the client."""
    payload: dict[str, object] = {"type": "exit", "code": code}
    if error:
        payload["error"] = error
    await websocket.send_text(json.dumps(payload))
