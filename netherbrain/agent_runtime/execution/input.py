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
from urllib.parse import urlparse

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
    from y_agent_environment import FileOperator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety limits
# ---------------------------------------------------------------------------

_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB -- saved to disk (tmp)
_MAX_INLINE_BYTES = 50 * 1024 * 1024  # 50 MB -- loaded into model context
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


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
# File-mode helpers (write via FileOperator, return path reference)
# ---------------------------------------------------------------------------


async def _download_url(
    url: str,
    file_operator: FileOperator,
    client: httpx.AsyncClient,
) -> str:
    """Download a URL to the agent's tmp directory via FileOperator.

    Returns a structured description of the downloaded file.

    Safety:
    - Only http/https schemes are allowed.
    - Downloads are capped at ``_MAX_DOWNLOAD_BYTES`` (stream-checked).
    - The Content-Length header is checked for early rejection.
    """
    # Validate URL scheme
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        msg = f"URL scheme not allowed: {parsed.scheme!r} (allowed: {', '.join(sorted(_ALLOWED_URL_SCHEMES))})"
        raise ValueError(msg)

    original_name = Path(parsed.path).name or "download"
    filename = f"{uuid.uuid4().hex[:8]}-{original_name}"

    # Stream download with size limit
    async with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()

        # Fast reject via Content-Length header (if present)
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > _MAX_DOWNLOAD_BYTES:
            msg = f"File too large: {content_length} bytes (limit: {_MAX_DOWNLOAD_BYTES})"
            raise ValueError(msg)

        # Stream with incremental size check
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                msg = f"Download exceeded size limit ({_MAX_DOWNLOAD_BYTES} bytes)"
                raise ValueError(msg)
            chunks.append(chunk)

        content = b"".join(chunks)

    content_type = response.headers.get("content-type", "unknown")
    abs_path = await file_operator.write_tmp_file(filename, content)
    logger.debug("Downloaded %s -> %s (%s, %d bytes)", url, abs_path, content_type, total)

    return f"[File downloaded from URL]\nSource: {url}\nSaved to: {abs_path}\nType: {content_type}\nSize: {total} bytes"


async def _write_binary(
    data: bytes,
    mime: str,
    file_operator: FileOperator,
) -> str:
    """Write binary data to the agent's tmp directory via FileOperator.

    Returns a structured description of the written file.

    Raises ``ValueError`` if data exceeds ``_MAX_DOWNLOAD_BYTES``.
    """
    if len(data) > _MAX_DOWNLOAD_BYTES:
        msg = f"Binary data too large: {len(data)} bytes (limit: {_MAX_DOWNLOAD_BYTES})"
        raise ValueError(msg)

    ext = mimetypes.guess_extension(mime) or ".bin"
    filename = f"{uuid.uuid4().hex[:12]}{ext}"

    abs_path = await file_operator.write_tmp_file(filename, data)
    logger.debug("Wrote binary (%s, %d bytes) -> %s", mime, len(data), abs_path)

    return f"[Binary data saved]\nSaved to: {abs_path}\nType: {mime}\nSize: {len(data)} bytes"


def _resolve_file_path(path: str) -> str:
    """Clean a relative file path for prompt embedding.

    Strips leading slashes and dot-slash prefixes, returning a clean
    relative path.  Path containment is enforced by FileOperator when
    the agent later accesses the file.
    """
    return path.lstrip("/").lstrip("./")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def map_input_to_prompt(
    parts: Sequence[InputPart],
    file_operator: FileOperator | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> str | list[UserContent]:
    """Map Netherbrain input parts to SDK UserPrompt.

    Parameters
    ----------
    parts:
        Input parts from the API request.
    file_operator:
        SDK FileOperator for file I/O.  Required for ``mode=file``
        operations on url/binary parts and ``mode=inline`` on file parts.
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
        If file-mode operations are requested without a file operator.
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
            content = await _map_single_part(part, file_operator, http_client)

            # If we need an HTTP client and don't have one, create one
            if content is _NEEDS_HTTP_CLIENT:
                if http_client is None:
                    import httpx

                    http_client = httpx.AsyncClient(timeout=30.0)
                    own_client = True
                content = await _map_single_part(part, file_operator, http_client)

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


async def _map_url_part(
    part: InputPart,
    file_operator: FileOperator | None,
    http_client: httpx.AsyncClient | None,
) -> UserContent | object:
    """Map a URL InputPart, with download fallback to inline on failure."""
    url = part.url or ""
    if part.mode == ContentMode.INLINE:
        return _url_to_inline_content(url, part.mime)
    # mode=file: download via FileOperator, fall back to inline on failure
    if file_operator is None:
        logger.debug("No file operator for URL download, falling back to inline: %s", url)
        return _url_to_inline_content(url, part.mime)
    if http_client is None:
        return _NEEDS_HTTP_CLIENT
    try:
        return await _download_url(url, file_operator, http_client)
    except Exception:
        logger.warning("Download failed for %s, falling back to inline", url, exc_info=True)
        return _url_to_inline_content(url, part.mime)


async def _map_single_part(
    part: InputPart,
    file_operator: FileOperator | None,
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
            return await _map_url_part(part, file_operator, http_client)

        case InputPartType.FILE:
            file_path = part.path or ""
            if part.mode == ContentMode.INLINE:
                if file_operator is None:
                    msg = "File operator required for inline file input"
                    raise ValueError(msg)
                return await _map_file_inline(file_path, part.mime, file_operator)
            # mode=file: reference the file by cleaned path
            clean_path = _resolve_file_path(file_path)
            return f"[Project file]\nPath: {clean_path}"

        case InputPartType.BINARY:
            return await _map_binary_part(part, file_operator)

        case _:
            msg = f"Unknown input part type: {part.type}"
            raise ValueError(msg)


async def _map_file_inline(
    file_path: str,
    mime: str | None,
    file_operator: FileOperator,
) -> UserContent:
    """Read a project file via FileOperator and return as inline BinaryContent.

    Raises ``ValueError`` if the file exceeds ``_MAX_INLINE_BYTES``.
    """
    clean = file_path.lstrip("/").lstrip("./")
    if not await file_operator.exists(clean):
        msg = f"File not found: {file_path}"
        raise FileNotFoundError(msg)
    file_data = await file_operator.read_bytes(clean)
    if len(file_data) > _MAX_INLINE_BYTES:
        msg = f"File too large for inline mode: {len(file_data)} bytes (limit: {_MAX_INLINE_BYTES})"
        raise ValueError(msg)
    resolved_mime = mime or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    return _bytes_to_inline_content(file_data, resolved_mime)


async def _map_binary_part(
    part: InputPart,
    file_operator: FileOperator | None,
) -> UserContent | str:
    """Map a binary InputPart to either inline content or a file reference."""
    raw = base64.b64decode(part.data or "", validate=True)
    mime = part.mime or "application/octet-stream"
    if part.mode == ContentMode.INLINE:
        if len(raw) > _MAX_INLINE_BYTES:
            msg = f"Binary data too large for inline mode: {len(raw)} bytes (limit: {_MAX_INLINE_BYTES})"
            raise ValueError(msg)
        return _bytes_to_inline_content(raw, mime)
    # mode=file: write via FileOperator
    if file_operator is None:
        msg = "File operator required for mode=file binary input"
        raise ValueError(msg)
    return await _write_binary(raw, mime, file_operator)
