"""Input mapping -- converts Netherbrain input parts to SDK UserPrompt.

Maps the ``list[InputPart]`` wire format to ``UserPromptT`` (the type
accepted by ``stream_agent(user_prompt=...)``).

Two delivery modes per part:

- **file** (default): Write content to the project directory and reference
  the path in a text instruction.  Safe for all models.
- **inline**: Pass content directly into the model context as multimodal
  ``UserContent``.  Model-dependent; fails if unsupported.

See spec/agent_runtime/03-execution.md (Input Mapping) for the full matrix.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    UserContent,
    VideoUrl,
)

from netherbrain.agent_runtime.models.enums import ContentMode, InputPartType
from netherbrain.agent_runtime.models.input import InputPart

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from netherbrain.agent_runtime.execution.environment import ProjectPaths

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MIME classification
# ---------------------------------------------------------------------------

_IMAGE_PREFIXES = ("image/",)
_AUDIO_PREFIXES = ("audio/",)
_VIDEO_PREFIXES = ("video/",)
_DOCUMENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/html",
    "text/csv",
    "text/markdown",
    "application/json",
}


def _classify_mime(mime: str | None) -> str:
    """Classify MIME type into a content category.

    Returns one of: 'image', 'audio', 'video', 'document', 'binary'.
    """
    if mime is None:
        return "binary"

    mime_lower = mime.lower().split(";")[0].strip()

    if any(mime_lower.startswith(p) for p in _IMAGE_PREFIXES):
        return "image"
    if any(mime_lower.startswith(p) for p in _AUDIO_PREFIXES):
        return "audio"
    if any(mime_lower.startswith(p) for p in _VIDEO_PREFIXES):
        return "video"
    if mime_lower in _DOCUMENT_TYPES or mime_lower.startswith("text/"):
        return "document"
    return "binary"


def _url_to_inline_content(url: str, mime: str | None) -> UserContent:
    """Map a URL + MIME to the appropriate pydantic-ai inline content type."""
    # Try to guess MIME from URL if not provided
    if mime is None:
        guessed, _ = mimetypes.guess_type(url)
        mime = guessed

    category = _classify_mime(mime)

    match category:
        case "image":
            return ImageUrl(url=url)
        case "audio":
            return AudioUrl(url=url)
        case "video":
            return VideoUrl(url=url)
        case "document":
            return DocumentUrl(url=url)
        case _:
            # Fall back to document URL for unknown types
            return DocumentUrl(url=url)


def _bytes_to_inline_content(data: bytes, mime: str) -> UserContent:
    """Map raw bytes + MIME to pydantic-ai BinaryContent."""
    return BinaryContent(data=data, media_type=mime)


# ---------------------------------------------------------------------------
# File-mode helpers (write to environment, return virtual path reference)
# ---------------------------------------------------------------------------


async def _download_url_to_project(
    url: str,
    paths: ProjectPaths,
    client: httpx.AsyncClient,
) -> str:
    """Download a URL to the default project's downloads directory.

    Returns the virtual path string for the downloaded file.
    """
    default_real = paths.default_real_path
    if default_real is None:
        msg = "Cannot download URL in file mode without a project directory"
        raise ValueError(msg)

    # Determine filename from URL
    from urllib.parse import urlparse

    parsed = urlparse(url)
    filename = Path(parsed.path).name or f"download-{uuid.uuid4().hex[:8]}"

    downloads_dir = default_real / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    # Avoid name collisions
    target = downloads_dir / filename
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        target = downloads_dir / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"

    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    target.write_bytes(response.content)

    # Return virtual path
    default_virtual = paths.default_virtual_path
    if default_virtual is None:  # pragma: no cover
        msg = "default_virtual_path is None despite default_real_path check"
        raise RuntimeError(msg)
    virtual_file = default_virtual / "downloads" / target.name
    logger.debug("Downloaded %s -> %s (virtual: %s)", url, target, virtual_file)
    return str(virtual_file)


def _write_binary_to_project(
    data: bytes,
    mime: str,
    paths: ProjectPaths,
) -> str:
    """Write binary data to the default project's tmp directory.

    Returns the virtual path string for the written file.
    """
    default_real = paths.default_real_path
    if default_real is None:
        msg = "Cannot write binary in file mode without a project directory"
        raise ValueError(msg)

    # Determine extension from MIME
    ext = mimetypes.guess_extension(mime) or ".bin"
    filename = f"{uuid.uuid4().hex[:12]}{ext}"

    tmp_dir = default_real / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / filename
    target.write_bytes(data)

    default_virtual = paths.default_virtual_path
    if default_virtual is None:  # pragma: no cover
        msg = "default_virtual_path is None despite default_real_path check"
        raise RuntimeError(msg)
    virtual_file = default_virtual / ".tmp" / filename
    logger.debug("Wrote binary (%s, %d bytes) -> %s", mime, len(data), virtual_file)
    return str(virtual_file)


def _resolve_file_path(path: str, paths: ProjectPaths) -> str:
    """Resolve a project-relative file path to a virtual path.

    The input ``path`` is relative to the default project.
    Returns the virtual path string.
    """
    default_virtual = paths.default_virtual_path
    if default_virtual is None:
        msg = "Cannot resolve file path without a project directory"
        raise ValueError(msg)

    # Normalize: strip leading slash or "./", treat as relative
    clean = path.lstrip("/").lstrip("./")
    return str(default_virtual / clean)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def map_input_to_prompt(
    parts: Sequence[InputPart],
    paths: ProjectPaths | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> str | list[UserContent]:
    """Map Netherbrain input parts to SDK UserPrompt.

    Parameters
    ----------
    parts:
        Input parts from the API request.
    paths:
        Resolved project paths.  Required for ``mode=file`` operations
        on url/file/binary parts.
    http_client:
        HTTP client for downloading URLs in ``mode=file``.  A temporary
        client is created if not provided.

    Returns
    -------
    str | list[UserContent]
        A simple string if all parts are text, or a list of ``UserContent``
        for multimodal input.  Suitable for ``stream_agent(user_prompt=...)``.

    Raises
    ------
    ValueError:
        If file-mode operations are requested without project paths.
    """
    if not parts:
        return ""

    # Fast path: single text part -> plain string
    if len(parts) == 1 and parts[0].type == InputPartType.TEXT:
        return parts[0].text or ""

    # Check if all parts are text -> can return simple concatenated string
    all_text = all(p.type == InputPartType.TEXT for p in parts)
    if all_text:
        return "\n\n".join(p.text or "" for p in parts)

    # Mixed content -> build a list of UserContent
    result: list[UserContent] = []
    own_client = False

    try:
        for part in parts:
            content = await _map_single_part(part, paths, http_client)

            # If we need an HTTP client and don't have one, create one
            if content is _NEEDS_HTTP_CLIENT:
                if http_client is None:
                    import httpx

                    http_client = httpx.AsyncClient(timeout=30.0)
                    own_client = True
                content = await _map_single_part(part, paths, http_client)

            if isinstance(content, str):
                result.append(content)
            else:
                result.append(content)  # type: ignore[arg-type]
    finally:
        if own_client and http_client is not None:
            await http_client.aclose()

    return result


# Sentinel for lazy HTTP client creation
_NEEDS_HTTP_CLIENT = object()


async def _map_single_part(
    part: InputPart,
    paths: ProjectPaths | None,
    http_client: httpx.AsyncClient | None,
) -> UserContent | object:
    """Map a single InputPart to a UserContent item.

    Returns ``_NEEDS_HTTP_CLIENT`` sentinel if an HTTP client is needed
    but not available.
    """
    match part.type:
        case InputPartType.TEXT:
            return part.text or ""

        case InputPartType.URL:
            url = part.url or ""
            if part.mode == ContentMode.INLINE:
                return _url_to_inline_content(url, part.mime)
            # mode=file: download to project
            if http_client is None:
                return _NEEDS_HTTP_CLIENT
            if paths is None:
                msg = "Project paths required for mode=file URL input"
                raise ValueError(msg)
            virtual_path = await _download_url_to_project(url, paths, http_client)
            return f"[Downloaded file: {virtual_path}]"

        case InputPartType.FILE:
            file_path = part.path or ""
            if paths is None:
                msg = "Project paths required for file input"
                raise ValueError(msg)
            if part.mode == ContentMode.INLINE:
                return _map_file_inline(file_path, part.mime, paths)
            # mode=file: resolve path
            virtual_path = _resolve_file_path(file_path, paths)
            return f"[See file: {virtual_path}]"

        case InputPartType.BINARY:
            return _map_binary_part(part, paths)

        case _:
            msg = f"Unknown input part type: {part.type}"
            raise ValueError(msg)


def _map_file_inline(
    file_path: str,
    mime: str | None,
    paths: ProjectPaths,
) -> UserContent:
    """Read a project file and return as inline BinaryContent."""
    clean = file_path.lstrip("/").lstrip("./")
    default_real = paths.default_real_path
    if default_real is None:
        msg = "Cannot read file without a project directory"
        raise ValueError(msg)
    real_file = default_real / clean
    if not real_file.exists():
        msg = f"File not found: {file_path}"
        raise FileNotFoundError(msg)
    file_data = real_file.read_bytes()
    resolved_mime = mime or mimetypes.guess_type(str(real_file))[0] or "application/octet-stream"
    return _bytes_to_inline_content(file_data, resolved_mime)


def _map_binary_part(
    part: InputPart,
    paths: ProjectPaths | None,
) -> UserContent | str:
    """Map a binary InputPart to either inline content or a file reference."""
    raw = base64.b64decode(part.data or "")
    mime = part.mime or "application/octet-stream"
    if part.mode == ContentMode.INLINE:
        return _bytes_to_inline_content(raw, mime)
    # mode=file: write to project temp
    if paths is None:
        msg = "Project paths required for mode=file binary input"
        raise ValueError(msg)
    virtual_path = _write_binary_to_project(raw, mime, paths)
    return f"[Binary file written: {virtual_path}]"
