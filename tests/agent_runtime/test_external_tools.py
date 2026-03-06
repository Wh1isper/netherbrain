"""Unit tests for external tools meta tool factory."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from netherbrain.agent_runtime.execution.external_tools import (
    _build_description,
    _execute_http_call,
    _validate_arguments,
    create_external_meta_tool,
)
from netherbrain.agent_runtime.models.api import ExternalToolSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(**overrides) -> ExternalToolSpec:
    """Create an ExternalToolSpec with sensible defaults."""
    defaults = {
        "name": "test_tool",
        "description": "A test tool",
        "parameters_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        "method": "POST",
        "url": "https://example.com/callback",
        "headers": {"Authorization": "Bearer test-token"},
        "timeout": 10,
    }
    defaults.update(overrides)
    return ExternalToolSpec(**defaults)


def _make_run_context():
    """Create a minimal mock RunContext."""
    ctx = AsyncMock()
    ctx.deps = None
    return ctx


# ---------------------------------------------------------------------------
# ExternalToolSpec model
# ---------------------------------------------------------------------------


def test_external_tool_spec_defaults() -> None:
    spec = ExternalToolSpec(
        name="my_tool",
        description="Does something",
        url="https://example.com/api",
    )
    assert spec.method == "POST"
    assert spec.headers == {}
    assert spec.parameters_schema == {}
    assert spec.timeout == 30


def test_external_tool_spec_full() -> None:
    spec = _make_spec()
    assert spec.name == "test_tool"
    assert spec.description == "A test tool"
    assert spec.method == "POST"
    assert spec.url == "https://example.com/callback"
    assert spec.headers == {"Authorization": "Bearer test-token"}
    assert spec.timeout == 10


def test_external_tool_spec_timeout_bounds() -> None:
    with pytest.raises(Exception):  # noqa: B017
        ExternalToolSpec(name="t", description="d", url="https://x.com", timeout=0)
    with pytest.raises(Exception):  # noqa: B017
        ExternalToolSpec(name="t", description="d", url="https://x.com", timeout=301)


# ---------------------------------------------------------------------------
# _validate_arguments
# ---------------------------------------------------------------------------


def test_validate_arguments_valid() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    assert _validate_arguments({"name": "hello"}, schema) is None


def test_validate_arguments_invalid() -> None:
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    result = _validate_arguments({"count": "not_a_number"}, schema)
    assert result is not None
    assert "validation failed" in result.lower()


def test_validate_arguments_missing_required() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    result = _validate_arguments({}, schema)
    assert result is not None
    assert "validation failed" in result.lower()


def test_validate_arguments_empty_schema() -> None:
    assert _validate_arguments({"any": "data"}, {}) is None


# ---------------------------------------------------------------------------
# _build_description
# ---------------------------------------------------------------------------


def test_build_description_single_tool() -> None:
    specs = [_make_spec(name="send_message", description="Send a message")]
    desc = _build_description(specs)
    assert "send_message" in desc
    assert "Send a message" in desc
    assert "Parameters:" in desc


def test_build_description_multiple_tools() -> None:
    specs = [
        _make_spec(name="tool_a", description="First tool"),
        _make_spec(name="tool_b", description="Second tool", parameters_schema={}),
    ]
    desc = _build_description(specs)
    assert "tool_a" in desc
    assert "tool_b" in desc
    assert "First tool" in desc
    assert "Second tool" in desc


def test_build_description_no_schema() -> None:
    specs = [_make_spec(name="simple", description="Simple tool", parameters_schema={})]
    desc = _build_description(specs)
    assert "simple" in desc
    # No "Parameters:" line for empty schema.
    assert "Parameters:" not in desc


# ---------------------------------------------------------------------------
# _execute_http_call
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_http_call_success() -> None:
    spec = _make_spec()
    mock_response = httpx.Response(200, text='{"result": "ok"}')

    with patch("netherbrain.agent_runtime.execution.external_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await _execute_http_call(spec, {"message": "hello"})

    assert result == '{"result": "ok"}'
    mock_client.request.assert_called_once_with(
        method="POST",
        url="https://example.com/callback",
        headers={"Authorization": "Bearer test-token"},
        json={"message": "hello"},
    )


@pytest.mark.anyio
async def test_execute_http_call_error_status() -> None:
    spec = _make_spec()
    mock_response = httpx.Response(500, text="Internal Server Error")

    with patch("netherbrain.agent_runtime.execution.external_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await _execute_http_call(spec, {})

    assert "500" in result
    assert "Internal Server Error" in result


@pytest.mark.anyio
async def test_execute_http_call_empty_success() -> None:
    spec = _make_spec()
    mock_response = httpx.Response(204, text="")

    with patch("netherbrain.agent_runtime.execution.external_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await _execute_http_call(spec, {})

    assert result == "(empty response)"


# ---------------------------------------------------------------------------
# create_external_meta_tool
# ---------------------------------------------------------------------------


def test_create_meta_tool_basic() -> None:
    specs = [_make_spec(name="greet", description="Greet someone")]
    tool = create_external_meta_tool(specs)

    assert tool.name == "call_external"
    assert "greet" in tool.description
    assert "Greet someone" in tool.description


def test_create_meta_tool_multiple_tools() -> None:
    specs = [
        _make_spec(name="tool_a", description="First"),
        _make_spec(name="tool_b", description="Second"),
    ]
    tool = create_external_meta_tool(specs)

    assert "tool_a" in tool.description
    assert "tool_b" in tool.description


@pytest.mark.anyio
async def test_meta_tool_unknown_name() -> None:
    specs = [_make_spec(name="known_tool")]
    tool = create_external_meta_tool(specs)

    ctx = _make_run_context()
    result = await tool.function(ctx, "unknown_tool", {})

    assert "Error" in result
    assert "unknown_tool" in result
    assert "known_tool" in result


@pytest.mark.anyio
async def test_meta_tool_validation_failure() -> None:
    specs = [
        _make_spec(
            name="strict_tool",
            parameters_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        )
    ]
    tool = create_external_meta_tool(specs)

    ctx = _make_run_context()
    result = await tool.function(ctx, "strict_tool", {"count": "not_int"})

    assert "Error" in result
    assert "validation failed" in result.lower()


@pytest.mark.anyio
async def test_meta_tool_successful_call() -> None:
    specs = [_make_spec(name="api_call")]
    tool = create_external_meta_tool(specs)

    mock_response = httpx.Response(200, text='{"status": "ok"}')

    with patch("netherbrain.agent_runtime.execution.external_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        ctx = _make_run_context()
        result = await tool.function(ctx, "api_call", {"message": "hi"})

    assert result == '{"status": "ok"}'


@pytest.mark.anyio
async def test_meta_tool_timeout_error() -> None:
    specs = [_make_spec(name="slow_tool", timeout=5, parameters_schema={})]
    tool = create_external_meta_tool(specs)

    with patch("netherbrain.agent_runtime.execution.external_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        ctx = _make_run_context()
        result = await tool.function(ctx, "slow_tool", {})

    assert "timed out" in result.lower()
    assert "slow_tool" in result


@pytest.mark.anyio
async def test_meta_tool_connection_error() -> None:
    specs = [_make_spec(name="unreachable", parameters_schema={})]
    tool = create_external_meta_tool(specs)

    with patch("netherbrain.agent_runtime.execution.external_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        ctx = _make_run_context()
        result = await tool.function(ctx, "unreachable", {})

    assert "Error" in result
    assert "unreachable" in result


@pytest.mark.anyio
async def test_meta_tool_uses_correct_http_method() -> None:
    specs = [_make_spec(name="get_tool", method="GET", parameters_schema={})]
    tool = create_external_meta_tool(specs)

    mock_response = httpx.Response(200, text="ok")

    with patch("netherbrain.agent_runtime.execution.external_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        ctx = _make_run_context()
        await tool.function(ctx, "get_tool", {})

    mock_client.request.assert_called_once_with(
        method="GET",
        url="https://example.com/callback",
        headers={"Authorization": "Bearer test-token"},
        json={},
    )


def test_meta_tool_deduplicates_names() -> None:
    """Last spec wins when duplicate names are provided."""
    specs = [
        _make_spec(name="dup", description="First"),
        _make_spec(name="dup", description="Second"),
    ]
    tool = create_external_meta_tool(specs)
    # The map uses last-wins semantics.
    assert "Second" in tool.description
