"""PTY process lifecycle and shell registry.

Provides interactive shell access via real PTY devices.  Uses
``os.openpty()`` + ``subprocess.Popen`` (not asyncio subprocess) so that
child processes see a real TTY -- required for programs like vim, htop,
and anything that checks ``isatty()``.

Async I/O on the master fd uses ``loop.add_reader()`` (epoll on Linux),
the same approach used by JupyterLab's terminado.  No extra threads.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import os
import signal
import struct
import subprocess
import termios
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_SHELLS = 10
"""Global limit on concurrent shell sessions."""

DEFAULT_COLS = 80
DEFAULT_ROWS = 24

_READ_SIZE = 65536
"""Bytes to read per os.read() call on the master fd."""

_CLOSE_TIMEOUT = 3.0
"""Seconds to wait for process exit after SIGHUP before SIGKILL."""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ShellLimitError(RuntimeError):
    """Raised when the global shell limit has been reached."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Shell limit reached ({limit} concurrent sessions)")


# ---------------------------------------------------------------------------
# PtyProcess
# ---------------------------------------------------------------------------


class PtyProcess:
    """Async wrapper around a PTY-backed child process.

    Intended to be used as an async context manager::

        async with PtyProcess.spawn("/bin/bash", cwd="/tmp") as pty:
            pty.write(b"ls\\n")
            data = await pty.read()

    The class manages the master/slave fd pair, child process lifecycle,
    and async read via ``loop.add_reader()``.
    """

    def __init__(
        self,
        master_fd: int,
        slave_fd: int,
        process: subprocess.Popen[bytes],
        *,
        shell_id: str,
    ) -> None:
        self._master_fd = master_fd
        self._slave_fd = slave_fd
        self._process = process
        self._shell_id = shell_id
        self._closed = False
        self._exit_code: int | None = None

        # Async read infrastructure.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._read_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._reader_installed = False

    @property
    def shell_id(self) -> str:
        return self._shell_id

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def is_alive(self) -> bool:
        return not self._closed and self._process.poll() is None

    # -- Factory ---------------------------------------------------------------

    @classmethod
    def spawn(
        cls,
        command: str | list[str] | None = None,
        *,
        cwd: str | Path | None = None,
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
        shell_id: str = "",
        env: dict[str, str] | None = None,
    ) -> PtyProcess:
        """Spawn a new PTY process.

        Parameters
        ----------
        command
            Shell command to execute.  Defaults to ``$SHELL`` or ``/bin/bash``.
        cwd
            Working directory for the child process.
        cols, rows
            Initial terminal dimensions.
        shell_id
            Identifier for logging and registry tracking.
        env
            Extra environment variables (merged with ``os.environ``).
        """
        if command is None:
            command = [os.environ.get("SHELL", "/bin/bash")]
        elif isinstance(command, str):
            command = [command]

        master_fd, slave_fd = os.openpty()

        # Set initial terminal size.
        _set_winsize(master_fd, cols, rows)

        # Build environment: inherit current env, overlay extras.
        child_env = os.environ.copy()
        child_env["TERM"] = child_env.get("TERM", "xterm-256color")
        if env:
            child_env.update(env)

        try:
            process = subprocess.Popen(  # noqa: S603
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env=child_env,
                start_new_session=True,  # New session -> own process group.
                close_fds=True,
            )
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise

        # Close the slave fd in the parent -- only the child needs it.
        os.close(slave_fd)

        logger.debug("PTY spawned: shell_id={}, pid={}, cmd={}", shell_id, process.pid, command)
        return cls(master_fd, -1, process, shell_id=shell_id)

    # -- Async context manager -------------------------------------------------

    async def __aenter__(self) -> PtyProcess:
        self._install_reader()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # -- I/O -------------------------------------------------------------------

    def _install_reader(self) -> None:
        """Register the master fd with the event loop for async reads."""
        if self._reader_installed:
            return
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(self._master_fd, self._on_readable)
        self._reader_installed = True

    def _on_readable(self) -> None:
        """Callback fired when the master fd has data (or EOF/EIO)."""
        try:
            data = os.read(self._master_fd, _READ_SIZE)
            if data:
                self._read_queue.put_nowait(data)
            else:
                # Empty read -> all slave fds closed (process exited).
                self._read_queue.put_nowait(None)
                self._remove_reader()
        except OSError as exc:
            if exc.errno == errno.EIO:
                # EIO is the normal signal that the slave side is gone.
                self._read_queue.put_nowait(None)
                self._remove_reader()
            else:
                logger.error("PTY read error: shell_id={}, errno={}", self._shell_id, exc.errno)
                self._read_queue.put_nowait(None)
                self._remove_reader()

    def _remove_reader(self) -> None:
        """Unregister the fd reader from the event loop."""
        if self._reader_installed and self._loop is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(self._master_fd)
            self._reader_installed = False

    async def read(self) -> bytes | None:
        """Read data from the PTY.

        Returns the next chunk of output, or ``None`` when the process
        has exited (EIO / empty read).
        """
        if self._closed:
            return None
        return await self._read_queue.get()

    def write(self, data: bytes) -> None:
        """Write data to the PTY (terminal input).

        Raises ``OSError`` if the master fd is closed.
        """
        if self._closed:
            return
        with contextlib.suppress(OSError):
            # fd already closed or process gone — suppress silently.
            os.write(self._master_fd, data)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY terminal.

        Sends ``TIOCSWINSZ`` ioctl.  The kernel delivers ``SIGWINCH``
        to the foreground process group automatically.
        """
        if self._closed:
            return
        with contextlib.suppress(OSError):
            _set_winsize(self._master_fd, cols, rows)

    # -- Lifecycle -------------------------------------------------------------

    async def close(self) -> int:
        """Gracefully close the PTY and terminate the child process.

        Sequence: SIGHUP -> wait -> SIGKILL (if still alive).
        Returns the exit code.
        """
        if self._closed:
            return self._exit_code or -1

        self._closed = True
        self._remove_reader()

        # Close the master fd first -- this causes the child to get EIO.
        with contextlib.suppress(OSError):
            os.close(self._master_fd)

        # Try graceful termination.
        exit_code = await self._terminate()
        self._exit_code = exit_code

        logger.debug("PTY closed: shell_id={}, pid={}, exit_code={}", self._shell_id, self._process.pid, exit_code)
        return exit_code

    async def _terminate(self) -> int:
        """Terminate the child process with escalating signals."""
        pid = self._process.pid

        # Check if already exited.
        code = self._process.poll()
        if code is not None:
            return code

        # Send SIGHUP to the process group.
        try:
            os.killpg(os.getpgid(pid), signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            code = self._process.poll()
            return code if code is not None else -1

        # Wait for exit.
        try:
            code = await asyncio.wait_for(
                asyncio.to_thread(self._process.wait),
                timeout=_CLOSE_TIMEOUT,
            )
        except TimeoutError:
            pass
        else:
            return code

        # Escalate to SIGKILL.
        logger.warning("PTY process {} did not exit after SIGHUP, sending SIGKILL", pid)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)

        try:
            code = await asyncio.wait_for(
                asyncio.to_thread(self._process.wait),
                timeout=2.0,
            )
        except TimeoutError:
            logger.error("PTY process {} did not exit after SIGKILL", pid)
            return -1
        else:
            return code

    def __del__(self) -> None:
        """Safety net: close the master fd if not already closed."""
        if not self._closed:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            # Best-effort kill.
            with contextlib.suppress(Exception):
                self._process.kill()


# ---------------------------------------------------------------------------
# ShellRegistry
# ---------------------------------------------------------------------------


class ShellRegistry:
    """Tracks active shell sessions with global connection limiting.

    Similar in spirit to ``SessionRegistry`` but for interactive shell
    connections.  Thread-safe within asyncio's cooperative scheduling.
    """

    def __init__(self, max_shells: int = DEFAULT_MAX_SHELLS) -> None:
        self._shells: dict[str, PtyProcess] = {}
        self._max_shells = max_shells

    @property
    def active_count(self) -> int:
        return len(self._shells)

    @property
    def max_shells(self) -> int:
        return self._max_shells

    def register(self, pty: PtyProcess) -> None:
        """Register an active shell session.

        Raises
        ------
        ShellLimitError
            If the maximum number of concurrent shells has been reached.
        """
        if len(self._shells) >= self._max_shells:
            raise ShellLimitError(self._max_shells)
        self._shells[pty.shell_id] = pty
        logger.debug("ShellRegistry: registered {} (active={})", pty.shell_id, len(self._shells))

    def unregister(self, shell_id: str) -> PtyProcess | None:
        """Remove a shell session from the registry."""
        pty = self._shells.pop(shell_id, None)
        if pty is not None:
            logger.debug("ShellRegistry: unregistered {} (active={})", shell_id, len(self._shells))
        return pty

    def get(self, shell_id: str) -> PtyProcess | None:
        return self._shells.get(shell_id)

    async def shutdown(self) -> None:
        """Close all active shell sessions.  Called during app shutdown."""
        if not self._shells:
            return
        logger.info("ShellRegistry: closing {} active shells", len(self._shells))
        shells = list(self._shells.values())
        self._shells.clear()
        await asyncio.gather(*(s.close() for s in shells), return_exceptions=True)
        logger.info("ShellRegistry: all shells closed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    """Set the terminal window size on a PTY fd."""
    # struct winsize: unsigned short rows, cols, xpixel, ypixel
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
