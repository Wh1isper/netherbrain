"""Local filesystem state store.

Stores session state as JSON files under a unified data root with optional
namespace prefix::

    {data_root}/{prefix}/sessions/{session_id}/state.json

When prefix is None, the path collapses to::

    {data_root}/sessions/{session_id}/state.json

Uses ``anyio.to_thread.run_sync`` for non-blocking file I/O.

Writes are atomic: data is written to a temporary file in the same directory,
then renamed to the target path.  This prevents corrupt reads if the process
crashes mid-write.

Display data (input, final_message) is stored in PostgreSQL on the session
row; only the heavy SDK state blob lives here.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from functools import partial
from pathlib import Path

from anyio import to_thread

from netherbrain.agent_runtime.models.session import SessionState


class LocalStateStore:
    """Local filesystem implementation of the StateStore protocol.

    Layout::

        {base}/sessions/{session_id}/state.json

    Where ``base`` is ``data_root / prefix`` (or just ``data_root`` if no prefix).
    """

    def __init__(self, data_root: str | Path, prefix: str | None = None) -> None:
        base = Path(data_root)
        if prefix:
            base = base / prefix
        self._base = base / "sessions"

    def _session_dir(self, session_id: str) -> Path:
        return self._base / session_id

    # -- Write -----------------------------------------------------------------

    async def write_state(self, session_id: str, state: SessionState) -> None:
        session_dir = self._session_dir(session_id)
        data = state.model_dump_json(indent=2)
        await to_thread.run_sync(partial(_atomic_write, session_dir / "state.json", data))

    # -- Read ------------------------------------------------------------------

    async def read_state(self, session_id: str) -> SessionState:
        path = self._session_dir(session_id) / "state.json"
        raw = await to_thread.run_sync(partial(_read_file, path))
        return SessionState.model_validate_json(raw)

    # -- Utilities -------------------------------------------------------------

    async def exists(self, session_id: str) -> bool:
        path = self._session_dir(session_id) / "state.json"
        return await to_thread.run_sync(path.exists)

    async def delete(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        await to_thread.run_sync(partial(_rmtree, session_dir))


# -- Sync helpers (run in thread pool) -----------------------------------------


def _atomic_write(path: Path, data: str) -> None:
    """Write data atomically: temp file + rename.

    Ensures readers never see a partially-written file.  The temp file is
    created in the same directory so ``os.rename`` is atomic on POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.rename(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _read_file(path: Path) -> str:
    """Read file contents.  Raises ``FileNotFoundError`` if missing."""
    return path.read_text(encoding="utf-8")


def _rmtree(path: Path) -> None:
    """Remove directory tree.  No-op if path doesn't exist."""
    if path.exists():
        shutil.rmtree(path)
