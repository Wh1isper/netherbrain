"""Unit tests for PTY process manager and shell registry.

Pure process tests -- no DB, no Docker, no integration markers.
Uses real PTY spawning on the host (requires Linux/macOS).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from netherbrain.agent_runtime.managers.shell import (
    DEFAULT_MAX_SHELLS,
    PtyProcess,
    ShellLimitError,
    ShellRegistry,
)

# Skip entire module on non-Unix platforms (no PTY support).
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY not available on Windows")


# ---------------------------------------------------------------------------
# PtyProcess tests
# ---------------------------------------------------------------------------


async def test_pty_spawn_and_read(tmp_path: Path) -> None:
    """Spawned PTY should produce output from an echo command."""
    pty = PtyProcess.spawn(
        ["/bin/sh", "-c", "echo hello_pty; exit 0"],
        cwd=tmp_path,
        shell_id="test-echo",
    )
    collected = b""
    async with pty:
        while True:
            data = await pty.read()
            if data is None:
                break
            collected += data

    assert b"hello_pty" in collected
    # Process exited cleanly.
    assert pty.exit_code == 0


async def test_pty_write_input(tmp_path: Path) -> None:
    """Writing to the PTY should be received by the child process."""
    pty = PtyProcess.spawn(
        ["/bin/sh"],
        cwd=tmp_path,
        shell_id="test-write",
    )
    collected = b""
    async with pty:
        # Send a command and then exit.
        pty.write(b"echo MARKER_XYZ\n")
        pty.write(b"exit\n")

        while True:
            data = await pty.read()
            if data is None:
                break
            collected += data

    assert b"MARKER_XYZ" in collected


async def test_pty_cwd(tmp_path: Path) -> None:
    """Child process should start in the specified cwd."""
    pty = PtyProcess.spawn(
        ["/bin/sh", "-c", "pwd; exit 0"],
        cwd=tmp_path,
        shell_id="test-cwd",
    )
    collected = b""
    async with pty:
        while True:
            data = await pty.read()
            if data is None:
                break
            collected += data

    # The output should contain the tmp_path (resolved).
    assert str(tmp_path.resolve()).encode() in collected


async def test_pty_resize(tmp_path: Path) -> None:
    """Resize should not raise (kernel sends SIGWINCH to child)."""
    pty = PtyProcess.spawn(
        ["/bin/sh"],
        cwd=tmp_path,
        shell_id="test-resize",
    )
    async with pty:
        # Should not raise.
        pty.resize(120, 40)
        pty.resize(80, 24)
        pty.write(b"exit\n")
        # Drain output.
        while await pty.read() is not None:
            pass


async def test_pty_close_returns_exit_code(tmp_path: Path) -> None:
    """Close should terminate the process and return exit code."""
    pty = PtyProcess.spawn(
        ["/bin/sh"],
        cwd=tmp_path,
        shell_id="test-close",
    )
    async with pty:
        pass  # __aexit__ calls close()

    # Should have an exit code after close.
    assert pty.exit_code is not None


async def test_pty_close_idempotent(tmp_path: Path) -> None:
    """Calling close() multiple times should be safe."""
    pty = PtyProcess.spawn(
        ["/bin/sh", "-c", "exit 42"],
        cwd=tmp_path,
        shell_id="test-idempotent",
    )
    async with pty:
        while await pty.read() is not None:
            pass

    code1 = await pty.close()
    code2 = await pty.close()
    assert code1 == code2


async def test_pty_read_after_close_returns_none(tmp_path: Path) -> None:
    """Reading from a closed PTY should return None."""
    pty = PtyProcess.spawn(
        ["/bin/sh", "-c", "exit 0"],
        cwd=tmp_path,
        shell_id="test-read-closed",
    )
    await pty.close()
    assert await pty.read() is None


async def test_pty_write_after_close_is_silent(tmp_path: Path) -> None:
    """Writing to a closed PTY should not raise."""
    pty = PtyProcess.spawn(
        ["/bin/sh", "-c", "exit 0"],
        cwd=tmp_path,
        shell_id="test-write-closed",
    )
    await pty.close()
    # Should not raise.
    pty.write(b"hello\n")


async def test_pty_is_alive(tmp_path: Path) -> None:
    """is_alive should reflect the process state."""
    pty = PtyProcess.spawn(
        ["/bin/sh"],
        cwd=tmp_path,
        shell_id="test-alive",
    )
    assert pty.is_alive is True
    await pty.close()
    assert pty.is_alive is False


async def test_pty_properties(tmp_path: Path) -> None:
    """Basic property accessors should work."""
    pty = PtyProcess.spawn(
        ["/bin/sh", "-c", "exit 0"],
        cwd=tmp_path,
        shell_id="test-props",
    )
    assert pty.shell_id == "test-props"
    assert pty.pid > 0
    assert pty.exit_code is None
    await pty.close()


async def test_pty_spawn_nonexistent_command(tmp_path: Path) -> None:
    """Spawning a nonexistent command should raise."""
    with pytest.raises(FileNotFoundError):
        PtyProcess.spawn(
            ["/nonexistent/command"],
            cwd=tmp_path,
            shell_id="test-bad-cmd",
        )


# ---------------------------------------------------------------------------
# ShellRegistry tests
# ---------------------------------------------------------------------------


async def test_registry_register_and_unregister(tmp_path: Path) -> None:
    """Register and unregister should track active shells."""
    registry = ShellRegistry()
    pty = PtyProcess.spawn(["/bin/sh", "-c", "exit 0"], cwd=tmp_path, shell_id="r-1")

    registry.register(pty)
    assert registry.active_count == 1
    assert registry.get("r-1") is pty

    removed = registry.unregister("r-1")
    assert removed is pty
    assert registry.active_count == 0
    assert registry.get("r-1") is None

    await pty.close()


async def test_registry_unregister_unknown() -> None:
    """Unregistering an unknown shell_id should return None."""
    registry = ShellRegistry()
    assert registry.unregister("nonexistent") is None


async def test_registry_limit(tmp_path: Path) -> None:
    """Exceeding the shell limit should raise ShellLimitError."""
    registry = ShellRegistry(max_shells=2)
    shells = []

    for i in range(2):
        pty = PtyProcess.spawn(["/bin/sh", "-c", "sleep 60"], cwd=tmp_path, shell_id=f"lim-{i}")
        registry.register(pty)
        shells.append(pty)

    assert registry.active_count == 2

    # Third shell should be rejected.
    pty3 = PtyProcess.spawn(["/bin/sh", "-c", "sleep 60"], cwd=tmp_path, shell_id="lim-2")
    with pytest.raises(ShellLimitError) as exc_info:
        registry.register(pty3)
    assert exc_info.value.limit == 2

    # Cleanup.
    await pty3.close()
    for pty in shells:
        registry.unregister(pty.shell_id)
        await pty.close()


async def test_registry_shutdown(tmp_path: Path) -> None:
    """Shutdown should close all active shells."""
    registry = ShellRegistry()
    shells = []

    for i in range(3):
        pty = PtyProcess.spawn(["/bin/sh", "-c", "sleep 60"], cwd=tmp_path, shell_id=f"sd-{i}")
        registry.register(pty)
        shells.append(pty)

    assert registry.active_count == 3

    await registry.shutdown()
    assert registry.active_count == 0

    # All processes should be terminated.
    for pty in shells:
        assert pty.is_alive is False


async def test_registry_default_limit() -> None:
    """Default max_shells should match the constant."""
    registry = ShellRegistry()
    assert registry.max_shells == DEFAULT_MAX_SHELLS


# ---------------------------------------------------------------------------
# WebSocket endpoint test (using Starlette TestClient)
# ---------------------------------------------------------------------------


def test_shell_websocket_requires_auth(tmp_path: Path) -> None:
    """WebSocket connection without auth token should be rejected."""
    from starlette.testclient import TestClient

    from netherbrain.agent_runtime.app import app
    from netherbrain.agent_runtime.managers.shell import ShellRegistry

    # Set minimal app state.
    app.state.auth_token = "test-token"  # noqa: S105
    app.state.jwt_secret = "test-jwt-secret-32bytes-minimum!"  # noqa: S105
    app.state.jwt_expiry_days = 7
    app.state.db_engine = None
    app.state.db_session_factory = None
    app.state.redis = None
    app.state.session_manager = None
    app.state.execution_manager = None
    app.state.shell_registry = ShellRegistry()

    client = TestClient(app)

    # No auth token -> should reject.
    with pytest.raises(Exception), client.websocket_connect("/api/shell/test-project/connect"):  # noqa: B017
        pass


def test_shell_websocket_project_not_found(tmp_path: Path) -> None:
    """WebSocket with auth but nonexistent project should close with policy violation."""
    import os

    from starlette.testclient import TestClient

    from netherbrain.agent_runtime.app import app
    from netherbrain.agent_runtime.managers.shell import ShellRegistry
    from netherbrain.agent_runtime.settings import _get_settings_cached

    token = "test-token-ws"  # noqa: S105

    # Point data_root to tmp_path so project lookup fails.
    os.environ["NETHER_DATA_ROOT"] = str(tmp_path)
    _get_settings_cached.cache_clear()

    app.state.auth_token = token
    app.state.jwt_secret = "test-jwt-secret-32bytes-minimum!"  # noqa: S105
    app.state.jwt_expiry_days = 7
    app.state.db_engine = None
    app.state.db_session_factory = None
    app.state.redis = None
    app.state.session_manager = None
    app.state.execution_manager = None
    app.state.shell_registry = ShellRegistry()

    client = TestClient(app)

    with pytest.raises(Exception), client.websocket_connect(f"/api/shell/nonexistent/connect?token={token}"):  # noqa: B017
        pass

    # Cleanup.
    os.environ.pop("NETHER_DATA_ROOT", None)
    _get_settings_cached.cache_clear()


def test_shell_websocket_full_session(tmp_path: Path) -> None:
    """Full WebSocket session: connect, send command, receive output, disconnect."""
    import json
    import os
    import time

    from starlette.testclient import TestClient

    from netherbrain.agent_runtime.app import app
    from netherbrain.agent_runtime.managers.shell import ShellRegistry
    from netherbrain.agent_runtime.settings import _get_settings_cached

    token = "test-token-ws-full"  # noqa: S105

    # Create a project directory.
    data_root = tmp_path / "data"
    projects = data_root / "projects" / "ws-project"
    projects.mkdir(parents=True)

    os.environ["NETHER_DATA_ROOT"] = str(data_root)
    _get_settings_cached.cache_clear()

    shell_registry = ShellRegistry()
    app.state.auth_token = token
    app.state.jwt_secret = "test-jwt-secret-32bytes-minimum!"  # noqa: S105
    app.state.jwt_expiry_days = 7
    app.state.db_engine = None
    app.state.db_session_factory = None
    app.state.redis = None
    app.state.session_manager = None
    app.state.execution_manager = None
    app.state.shell_registry = shell_registry

    client = TestClient(app)

    with client.websocket_connect(f"/api/shell/ws-project/connect?token={token}") as ws:
        # Give the PTY a moment to initialize and send its prompt.
        time.sleep(0.3)

        # Send a command.
        ws.send_bytes(b"echo WS_TEST_MARKER\n")

        # Collect output until we see our marker.
        collected = b""
        for _ in range(50):  # Safety limit.
            msg = ws.receive()
            if msg.get("bytes"):
                collected += msg["bytes"]
                if b"WS_TEST_MARKER" in collected:
                    break
            elif msg.get("text"):
                # Could be a control frame (exit), skip.
                continue
            else:
                break

        assert b"WS_TEST_MARKER" in collected

        # Test resize (should not error).
        ws.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))

        # Exit the shell.
        ws.send_bytes(b"exit\n")

    # Cleanup.
    os.environ.pop("NETHER_DATA_ROOT", None)
    _get_settings_cached.cache_clear()
