"""File operations for managed project directories.

Pure filesystem operations -- no database involvement.  All paths are
resolved relative to a project root directory under the data storage area.

Path layout: ``{data_root}/{data_prefix}/projects/{project_id}/``

Raises domain exceptions:

- ``LookupError``: project or path not found
- ``PermissionError``: path traversal or symlink escape attempt
- ``ValueError``: binary file, oversized content, or invalid input
"""

from __future__ import annotations

import contextlib
import mimetypes
import os
import tempfile
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Response models (plain Pydantic, framework-agnostic)
# ---------------------------------------------------------------------------


class FileEntry(BaseModel):
    """Single directory entry."""

    name: str
    path: str
    type: str  # "file" or "directory"
    size: int | None = None
    modified: datetime | None = None


class FileListResult(BaseModel):
    """Directory listing result."""

    project_id: str
    path: str
    entries: list[FileEntry]


class FileReadResult(BaseModel):
    """File content result."""

    project_id: str
    path: str
    content: str
    size: int
    modified: datetime
    truncated: bool
    encoding: str = "utf-8"


class FileWriteResult(BaseModel):
    """File write result."""

    project_id: str
    path: str
    size: int
    modified: datetime


class UploadedFileInfo(BaseModel):
    """Single uploaded file info."""

    path: str
    size: int


class UploadResult(BaseModel):
    """Upload operation result."""

    project_id: str
    uploaded: list[UploadedFileInfo]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BINARY_CHECK_SIZE = 8192
"""Number of bytes to inspect for null-byte binary detection."""

DEFAULT_MAX_READ = 1_048_576  # 1 MB
DEFAULT_MAX_UPLOAD_FILE = 100 * 1024 * 1024  # 100 MB
DEFAULT_MAX_ARCHIVE = 500 * 1024 * 1024  # 500 MB


# ---------------------------------------------------------------------------
# Path resolver
# ---------------------------------------------------------------------------


class ProjectPathResolver:
    """Resolves and validates paths within a project directory.

    Central security component.  Used by all file operations to ensure
    that the resolved path does not escape the project root.
    """

    def __init__(self, data_root: str, data_prefix: str | None = None) -> None:
        base = Path(data_root)
        if data_prefix:
            base = base / data_prefix
        self._projects_base = base / "projects"

    def project_root(self, project_id: str) -> Path:
        """Return the resolved project root path.

        Raises ``LookupError`` if the project directory does not exist.
        """
        project_dir = self._projects_base / project_id
        if not project_dir.is_dir():
            msg = f"Project '{project_id}' not found"
            raise LookupError(msg)
        return project_dir.resolve()

    def resolve(self, project_id: str, relative_path: str = "") -> Path:
        """Resolve a relative path within a project to a real filesystem path.

        Raises:
            LookupError: If the project directory does not exist.
            PermissionError: If the resolved path escapes the project root.
        """
        root_real = self.project_root(project_id)

        if not relative_path or relative_path in (".", "/"):
            return root_real

        target = (root_real / relative_path).resolve()

        # Ensure target is within (or equal to) project root
        if target != root_real and root_real not in target.parents:
            msg = "Path escapes project directory"
            raise PermissionError(msg)

        # Reject symlinks that point outside the project root
        raw_target = root_real / relative_path
        if raw_target.is_symlink():
            link_dest = raw_target.resolve()
            if link_dest != root_real and root_real not in link_dest.parents:
                msg = "Symlink escapes project directory"
                raise PermissionError(msg)

        return target


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


def list_directory(
    resolver: ProjectPathResolver,
    project_id: str,
    path: str = "",
) -> FileListResult:
    """List directory contents.

    Entries are sorted: directories first (alphabetical), then files
    (alphabetical).  Case-insensitive sorting.
    """
    target = resolver.resolve(project_id, path)

    if not target.is_dir():
        msg = f"Not a directory: {path}"
        raise LookupError(msg)

    root_real = resolver.project_root(project_id)
    dirs: list[FileEntry] = []
    files: list[FileEntry] = []

    with os.scandir(target) as entries:
        for entry in entries:
            entry_path = Path(entry.path).resolve()
            rel = str(entry_path.relative_to(root_real))
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue  # skip broken symlinks / permission errors
            modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

            fe = FileEntry(
                name=entry.name,
                path=rel,
                type="directory" if entry.is_dir() else "file",
                size=stat.st_size if entry.is_file() else None,
                modified=modified,
            )
            if entry.is_dir():
                dirs.append(fe)
            else:
                files.append(fe)

    dirs.sort(key=lambda e: e.name.lower())
    files.sort(key=lambda e: e.name.lower())

    return FileListResult(
        project_id=project_id,
        path=path or "",
        entries=dirs + files,
    )


def _is_binary(data: bytes) -> bool:
    """Check if data contains null bytes (binary file indicator)."""
    return b"\x00" in data


def read_file(
    resolver: ProjectPathResolver,
    project_id: str,
    path: str,
    max_size: int = DEFAULT_MAX_READ,
) -> FileReadResult:
    """Read a text file's content.

    Raises ``LookupError`` if the file does not exist.
    Raises ``ValueError`` if the file appears to be binary.
    """
    target = resolver.resolve(project_id, path)

    if not target.is_file():
        msg = f"File not found: {path}"
        raise LookupError(msg)

    stat = target.stat()
    size = stat.st_size
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    # Read up to max_size + 1 to detect truncation
    with open(target, "rb") as f:
        raw = f.read(max_size + 1)

    # Binary check on first 8 KB
    if _is_binary(raw[:BINARY_CHECK_SIZE]):
        msg = f"Binary file: {path}"
        raise ValueError(msg)

    truncated = len(raw) > max_size
    if truncated:
        raw = raw[:max_size]

    encoding = "utf-8"
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
        encoding = "latin-1"

    return FileReadResult(
        project_id=project_id,
        path=path,
        content=content,
        size=size,
        modified=modified,
        truncated=truncated,
        encoding=encoding,
    )


def write_file(
    resolver: ProjectPathResolver,
    project_id: str,
    path: str,
    content: str,
) -> FileWriteResult:
    """Write text content to a file.

    Uses atomic write (temp file + rename).  Parent directories are
    auto-created if they do not exist.
    """
    # Resolve validates path safety; target may not exist yet for new files,
    # so we resolve the parent directory instead.
    root_real = resolver.project_root(project_id)
    target = (root_real / path).resolve()

    # Safety: ensure target is within project root
    if target != root_real and root_real not in target.parents:
        msg = "Path escapes project directory"
        raise PermissionError(msg)

    # Auto-create parent directories
    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temp file, then rename
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    stat = target.stat()
    return FileWriteResult(
        project_id=project_id,
        path=path,
        size=stat.st_size,
        modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def save_upload(
    resolver: ProjectPathResolver,
    project_id: str,
    target_dir: str,
    filename: str,
    data: bytes,
    *,
    max_file_size: int = DEFAULT_MAX_UPLOAD_FILE,
) -> UploadedFileInfo:
    """Save a single uploaded file.

    Raises ``ValueError`` if the file exceeds the size limit.
    """
    if len(data) > max_file_size:
        msg = f"File '{filename}' exceeds size limit ({max_file_size} bytes)"
        raise ValueError(msg)

    # Build the relative path within the project
    rel_path = f"{target_dir}/{filename}" if target_dir else filename

    # Resolve and validate (write_file-style: resolve parent, check bounds)
    root_real = resolver.project_root(project_id)
    file_path = (root_real / rel_path).resolve()

    if file_path != root_real and root_real not in file_path.parents:
        msg = "Path escapes project directory"
        raise PermissionError(msg)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(data)

    return UploadedFileInfo(path=rel_path, size=len(data))


def resolve_download(
    resolver: ProjectPathResolver,
    project_id: str,
    path: str,
) -> tuple[Path, str]:
    """Resolve a file path for download.

    Returns ``(real_path, mime_type)`` for streaming.
    Raises ``LookupError`` if the file does not exist.
    """
    target = resolver.resolve(project_id, path)

    if not target.is_file():
        msg = f"File not found: {path}"
        raise LookupError(msg)

    mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return target, mime_type


def delete_path(
    resolver: ProjectPathResolver,
    project_id: str,
    path: str,
) -> None:
    """Delete a file or directory (recursively).

    Raises ``LookupError`` if the path does not exist.
    Raises ``PermissionError`` if path escapes project directory.
    Raises ``ValueError`` if attempting to delete the project root.
    """
    if not path or path in (".", "/"):
        msg = "Cannot delete project root"
        raise ValueError(msg)

    target = resolver.resolve(project_id, path)

    if not target.exists():
        msg = f"Path not found: {path}"
        raise LookupError(msg)

    import shutil

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def create_directory(
    resolver: ProjectPathResolver,
    project_id: str,
    path: str,
) -> None:
    """Create a directory (including parents).

    Raises ``PermissionError`` if path escapes project directory.
    Raises ``ValueError`` if the directory already exists.
    """
    if not path or path in (".", "/"):
        msg = "Cannot create project root"
        raise ValueError(msg)

    root_real = resolver.project_root(project_id)
    target = (root_real / path).resolve()

    # Safety: ensure target is within project root
    if target != root_real and root_real not in target.parents:
        msg = "Path escapes project directory"
        raise PermissionError(msg)

    if target.exists():
        msg = f"Already exists: {path}"
        raise ValueError(msg)

    target.mkdir(parents=True, exist_ok=False)


def build_archive(
    resolver: ProjectPathResolver,
    project_id: str,
    paths: Sequence[str],
    *,
    max_total_size: int = DEFAULT_MAX_ARCHIVE,
) -> BytesIO:
    """Build a zip archive from the given paths.

    Directories are included recursively.  Raises ``ValueError`` if total
    uncompressed size exceeds *max_total_size*.
    """
    root_real = resolver.project_root(project_id)

    # Collect all files with their archive names
    file_list: list[tuple[Path, str]] = []  # (real_path, archive_name)
    total_size = 0

    for p in paths:
        target = resolver.resolve(project_id, p)
        if not target.exists():
            msg = f"Path not found: {p}"
            raise LookupError(msg)
        if target.is_file():
            total_size += target.stat().st_size
            rel = str(target.relative_to(root_real))
            file_list.append((target, rel))
        elif target.is_dir():
            for root, _dirs, fnames in os.walk(target):
                root_path = Path(root)
                for fname in fnames:
                    fpath = root_path / fname
                    rel = str(fpath.relative_to(root_real))
                    total_size += fpath.stat().st_size
                    file_list.append((fpath, rel))

    if total_size > max_total_size:
        msg = f"Archive exceeds size limit ({total_size} > {max_total_size} bytes)"
        raise ValueError(msg)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for real_path, archive_name in file_list:
            zf.write(real_path, archive_name)

    buf.seek(0)
    return buf
