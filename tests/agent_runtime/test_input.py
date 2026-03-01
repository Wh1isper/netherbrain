"""Unit tests for input models and input mapping."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import AudioUrl, BinaryContent, DocumentUrl, ImageUrl, VideoUrl

from netherbrain.agent_runtime.execution.environment import ProjectPaths
from netherbrain.agent_runtime.execution.input import (
    _classify_mime,
    _resolve_file_path,
    _url_to_inline_content,
    _write_binary_to_project,
    map_input_to_prompt,
)
from netherbrain.agent_runtime.models.enums import ContentMode, InputPartType
from netherbrain.agent_runtime.models.input import (
    InputPart,
    ToolResult,
    UserInteraction,
    binary_part,
    file_part,
    text_part,
    url_part,
)

# ---------------------------------------------------------------------------
# InputPart model validation
# ---------------------------------------------------------------------------


def test_input_part_text_valid() -> None:
    p = InputPart(type=InputPartType.TEXT, text="hello")
    assert p.text == "hello"
    assert p.mode == ContentMode.FILE  # default


def test_input_part_text_missing_payload() -> None:
    with pytest.raises(ValueError, match="text field is required"):
        InputPart(type=InputPartType.TEXT)


def test_input_part_url_valid() -> None:
    p = InputPart(type=InputPartType.URL, url="https://example.com/image.png", mime="image/png")
    assert p.url == "https://example.com/image.png"


def test_input_part_url_missing_payload() -> None:
    with pytest.raises(ValueError, match="url field is required"):
        InputPart(type=InputPartType.URL)


def test_input_part_file_valid() -> None:
    p = InputPart(type=InputPartType.FILE, path="src/main.py")
    assert p.path == "src/main.py"


def test_input_part_file_missing_payload() -> None:
    with pytest.raises(ValueError, match="path field is required"):
        InputPart(type=InputPartType.FILE)


def test_input_part_binary_valid() -> None:
    data = base64.b64encode(b"hello").decode()
    p = InputPart(type=InputPartType.BINARY, data=data, mime="text/plain")
    assert p.data == data


def test_input_part_binary_missing_payload() -> None:
    with pytest.raises(ValueError, match="data field is required"):
        InputPart(type=InputPartType.BINARY)


def test_input_part_inline_mode() -> None:
    p = InputPart(type=InputPartType.URL, url="https://x.com/img.jpg", mode=ContentMode.INLINE)
    assert p.mode == ContentMode.INLINE


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def test_text_part() -> None:
    p = text_part("hello world")
    assert p.type == InputPartType.TEXT
    assert p.text == "hello world"


def test_url_part() -> None:
    p = url_part("https://example.com/photo.jpg", mime="image/jpeg", mode=ContentMode.INLINE)
    assert p.type == InputPartType.URL
    assert p.url == "https://example.com/photo.jpg"
    assert p.mime == "image/jpeg"
    assert p.mode == ContentMode.INLINE


def test_file_part() -> None:
    p = file_part("docs/readme.md")
    assert p.type == InputPartType.FILE
    assert p.path == "docs/readme.md"


def test_binary_part() -> None:
    data = base64.b64encode(b"bytes").decode()
    p = binary_part(data, mime="application/pdf")
    assert p.type == InputPartType.BINARY
    assert p.data == data
    assert p.mime == "application/pdf"


# ---------------------------------------------------------------------------
# Deferred tool feedback models
# ---------------------------------------------------------------------------


def test_user_interaction() -> None:
    ui = UserInteraction(tool_call_id="tc-1", approved=True)
    assert ui.tool_call_id == "tc-1"
    assert ui.approved is True


def test_tool_result() -> None:
    tr = ToolResult(tool_call_id="tc-2", output="done")
    assert tr.tool_call_id == "tc-2"
    assert tr.output == "done"
    assert tr.error is None


def test_tool_result_with_error() -> None:
    tr = ToolResult(tool_call_id="tc-3", error="timeout")
    assert tr.error == "timeout"


# ---------------------------------------------------------------------------
# MIME classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mime", "expected"),
    [
        ("image/png", "image"),
        ("image/jpeg", "image"),
        ("image/webp", "image"),
        ("audio/mp3", "audio"),
        ("audio/wav", "audio"),
        ("video/mp4", "video"),
        ("video/webm", "video"),
        ("application/pdf", "document"),
        ("text/plain", "document"),
        ("text/html", "document"),
        ("text/csv", "document"),
        ("application/json", "document"),
        ("application/octet-stream", "binary"),
        ("application/zip", "binary"),
        (None, "binary"),
        ("image/png; charset=utf-8", "image"),
    ],
)
def test_classify_mime(mime: str | None, expected: str) -> None:
    assert _classify_mime(mime) == expected


# ---------------------------------------------------------------------------
# URL inline mapping
# ---------------------------------------------------------------------------


def test_url_to_inline_image() -> None:
    result = _url_to_inline_content("https://x.com/photo.jpg", "image/jpeg")
    assert isinstance(result, ImageUrl)
    assert result.url == "https://x.com/photo.jpg"


def test_url_to_inline_audio() -> None:
    result = _url_to_inline_content("https://x.com/clip.mp3", "audio/mpeg")
    assert isinstance(result, AudioUrl)


def test_url_to_inline_video() -> None:
    result = _url_to_inline_content("https://x.com/vid.mp4", "video/mp4")
    assert isinstance(result, VideoUrl)


def test_url_to_inline_document() -> None:
    result = _url_to_inline_content("https://x.com/doc.pdf", "application/pdf")
    assert isinstance(result, DocumentUrl)


def test_url_to_inline_guess_mime() -> None:
    result = _url_to_inline_content("https://x.com/pic.png", None)
    assert isinstance(result, ImageUrl)


def test_url_to_inline_unknown_mime() -> None:
    result = _url_to_inline_content("https://x.com/data", None)
    # Unknown -> DocumentUrl fallback
    assert isinstance(result, DocumentUrl)


# ---------------------------------------------------------------------------
# File-mode helpers
# ---------------------------------------------------------------------------


def _make_paths(tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(
        data_root=tmp_path,
        prefix=None,
        project_ids=["test-proj"],
    )


def test_resolve_file_path(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    result = _resolve_file_path("src/main.py", paths)
    assert result == "/workspace/test-proj/src/main.py"


def test_resolve_file_path_leading_slash(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    result = _resolve_file_path("/src/main.py", paths)
    assert result == "/workspace/test-proj/src/main.py"


def test_resolve_file_path_leading_dot_slash(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    result = _resolve_file_path("./src/main.py", paths)
    assert result == "/workspace/test-proj/src/main.py"


def test_write_binary_to_project(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.ensure_directories()

    result = _write_binary_to_project(b"hello", "text/plain", paths)
    assert result.startswith("/workspace/test-proj/.tmp/")
    assert result.endswith(".txt")

    # Verify file was written
    real_path = paths.default_real_path
    assert real_path is not None
    tmp_dir = real_path / ".tmp"
    assert tmp_dir.exists()
    files = list(tmp_dir.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"hello"


# ---------------------------------------------------------------------------
# map_input_to_prompt (async)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_map_empty_input() -> None:
    result = await map_input_to_prompt([])
    assert result == ""


@pytest.mark.anyio
async def test_map_single_text() -> None:
    parts = [text_part("hello")]
    result = await map_input_to_prompt(parts)
    assert result == "hello"
    assert isinstance(result, str)


@pytest.mark.anyio
async def test_map_multiple_text() -> None:
    parts = [text_part("hello"), text_part("world")]
    result = await map_input_to_prompt(parts)
    assert result == "hello\n\nworld"
    assert isinstance(result, str)


@pytest.mark.anyio
async def test_map_inline_url() -> None:
    parts = [
        text_part("Look at this image:"),
        url_part("https://x.com/photo.jpg", mime="image/jpeg", mode=ContentMode.INLINE),
    ]
    result = await map_input_to_prompt(parts)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0] == "Look at this image:"
    assert isinstance(result[1], ImageUrl)


@pytest.mark.anyio
async def test_map_inline_binary() -> None:
    raw = b"PNG data here"
    data_b64 = base64.b64encode(raw).decode()
    parts = [binary_part(data_b64, mime="image/png", mode=ContentMode.INLINE)]
    result = await map_input_to_prompt(parts)
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], BinaryContent)
    assert result[0].data == raw


@pytest.mark.anyio
async def test_map_file_mode_file_part(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.ensure_directories()

    parts = [file_part("src/main.py")]
    result = await map_input_to_prompt(parts, paths)
    assert isinstance(result, list)
    assert "[See file: /workspace/test-proj/src/main.py]" in result[0]


@pytest.mark.anyio
async def test_map_file_mode_binary_part(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.ensure_directories()

    raw = b"binary content"
    data_b64 = base64.b64encode(raw).decode()
    parts = [binary_part(data_b64, mime="application/pdf")]
    result = await map_input_to_prompt(parts, paths)
    assert isinstance(result, list)
    assert "[Binary file written:" in result[0]


@pytest.mark.anyio
async def test_map_inline_file_part(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.ensure_directories()

    # Create a real file
    real_dir = paths.default_real_path
    assert real_dir is not None
    src_dir = real_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_bytes(b"print('hello')")

    parts = [file_part("src/main.py", mode=ContentMode.INLINE)]
    result = await map_input_to_prompt(parts, paths)
    assert isinstance(result, list)
    assert isinstance(result[0], BinaryContent)
    assert result[0].data == b"print('hello')"


@pytest.mark.anyio
async def test_map_inline_file_not_found(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.ensure_directories()

    parts = [file_part("nonexistent.py", mode=ContentMode.INLINE)]
    with pytest.raises(FileNotFoundError, match=r"nonexistent\.py"):
        await map_input_to_prompt(parts, paths)


@pytest.mark.anyio
async def test_map_file_mode_url_downloads(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.ensure_directories()

    # Mock HTTP client
    mock_response = MagicMock()
    mock_response.content = b"downloaded content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()

    parts = [url_part("https://example.com/file.txt")]
    result = await map_input_to_prompt(parts, paths, http_client=mock_client)

    assert isinstance(result, list)
    assert "[Downloaded file:" in result[0]

    # Verify file was actually written
    downloads_dir = paths.default_real_path / "downloads"  # type: ignore[operator]
    assert downloads_dir.exists()
    files = list(downloads_dir.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"downloaded content"


@pytest.mark.anyio
async def test_map_mixed_text_and_inline() -> None:
    parts = [
        text_part("Analyze this image:"),
        url_part("https://x.com/img.png", mime="image/png", mode=ContentMode.INLINE),
        text_part("And this document:"),
        url_part("https://x.com/doc.pdf", mime="application/pdf", mode=ContentMode.INLINE),
    ]
    result = await map_input_to_prompt(parts)
    assert isinstance(result, list)
    assert len(result) == 4
    assert result[0] == "Analyze this image:"
    assert isinstance(result[1], ImageUrl)
    assert result[2] == "And this document:"
    assert isinstance(result[3], DocumentUrl)


@pytest.mark.anyio
async def test_map_no_paths_for_file_mode_raises() -> None:
    parts = [file_part("some/file.txt")]
    with pytest.raises(ValueError, match="Project paths required"):
        await map_input_to_prompt(parts, None)
