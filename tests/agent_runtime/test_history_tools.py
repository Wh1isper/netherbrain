"""Tests for conversation history toolset (BaseTool subclasses).

Covers pure formatting, config extraction, availability checks,
and HTTP-level behaviour (mocked -- no real server needed).
"""

from __future__ import annotations

import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from ya_agent_sdk.context import ToolConfig

from netherbrain.agent_runtime.toolsets.common import get_nether_config
from netherbrain.agent_runtime.toolsets.history import (
    SearchConversationsTool,
    SummarizeConversationTool,
    format_search_results,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(**extras: object) -> MagicMock:
    """Build a mock ``RunContext[AgentContext]`` with ToolConfig extras."""
    tc = ToolConfig(**extras)
    ctx = MagicMock()
    ctx.deps.tool_config = tc
    return ctx


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    """Build a real ``httpx.Response`` with the given status and JSON body."""
    content = _json.dumps(json_data or {}).encode()
    return httpx.Response(status_code=status_code, content=content, headers={"content-type": "application/json"})


def _patch_client(response: httpx.Response, method: str = "get"):
    """Patch ``_build_client`` to return an async-context mock returning *response*."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    setattr(mock_client, method, AsyncMock(return_value=response))
    return patch("netherbrain.agent_runtime.toolsets.history.build_client", return_value=mock_client)


# ---------------------------------------------------------------------------
# format_search_results (pure unit -- no mocking)
# ---------------------------------------------------------------------------


def test_format_search_results_empty() -> None:
    data: dict = {"conversations": [], "total": 0, "has_more": False}
    assert format_search_results(data, "test") == "No conversations found matching 'test'."


def test_format_search_results_single_with_summary() -> None:
    data = {
        "conversations": [
            {"conversation_id": "c-1", "summary": "About Python", "title": "Chat", "match_source": "summary"},
        ],
        "total": 1,
        "has_more": False,
    }
    result = format_search_results(data, "python")
    assert "Found 1 conversation(s)" in result
    assert "[c-1] About Python (matched in: summary)" in result


def test_format_search_results_title_fallback() -> None:
    data = {
        "conversations": [
            {"conversation_id": "c-2", "summary": None, "title": "My Chat", "match_source": "title"},
        ],
        "total": 1,
        "has_more": False,
    }
    result = format_search_results(data, "chat")
    assert "[c-2] My Chat" in result


def test_format_search_results_untitled_fallback() -> None:
    data = {
        "conversations": [
            {"conversation_id": "c-3", "summary": None, "title": None, "match_source": "session_content"},
        ],
        "total": 1,
        "has_more": False,
    }
    assert "(untitled)" in format_search_results(data, "query")


def test_format_search_results_has_more() -> None:
    data = {
        "conversations": [
            {"conversation_id": "c-1", "summary": "A", "match_source": "title"},
        ],
        "total": 5,
        "has_more": True,
    }
    assert "... and 4 more." in format_search_results(data, "q")


def test_format_search_results_multiple() -> None:
    data = {
        "conversations": [
            {"conversation_id": "c-1", "summary": "First", "match_source": "summary"},
            {"conversation_id": "c-2", "title": "Second", "summary": None, "match_source": "title"},
        ],
        "total": 2,
        "has_more": False,
    }
    lines = format_search_results(data, "multi").strip().split("\n")
    assert len(lines) == 3  # header + 2 results
    assert "Found 2" in lines[0]


# ---------------------------------------------------------------------------
# _get_nether_config
# ---------------------------------------------------------------------------


def test_get_nether_config_extracts_all() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="secret",
        nether_conversation_id="conv-42",
    )
    url, token, cid = get_nether_config(ctx)
    assert url == "http://localhost:9001"
    assert token == "secret"  # noqa: S105
    assert cid == "conv-42"


def test_get_nether_config_defaults_empty() -> None:
    ctx = _make_ctx()
    url, token, cid = get_nether_config(ctx)
    assert url == ""
    assert token == ""
    assert cid == ""


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_when_api_url_set() -> None:
    ctx = _make_ctx(nether_api_base_url="http://localhost:9001")
    assert SearchConversationsTool().is_available(ctx) is True
    assert SummarizeConversationTool().is_available(ctx) is True


def test_unavailable_when_no_api_url() -> None:
    ctx = _make_ctx()
    assert SearchConversationsTool().is_available(ctx) is False
    assert SummarizeConversationTool().is_available(ctx) is False


def test_unavailable_when_empty_api_url() -> None:
    ctx = _make_ctx(nether_api_base_url="")
    assert SearchConversationsTool().is_available(ctx) is False


# ---------------------------------------------------------------------------
# SearchConversationsTool.call
# ---------------------------------------------------------------------------


async def test_search_call_success() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="tok",
        nether_conversation_id="conv-1",
    )
    json_data = {
        "conversations": [
            {"conversation_id": "c-1", "summary": "Python tips", "match_source": "summary"},
        ],
        "total": 1,
        "has_more": False,
    }
    with _patch_client(_mock_response(200, json_data)):
        result = await SearchConversationsTool().call(ctx, query="python")
    assert "Found 1 conversation(s)" in result


async def test_search_call_http_error() -> None:
    ctx = _make_ctx(nether_api_base_url="http://localhost:9001", nether_auth_token="tok")
    with _patch_client(_mock_response(500)):
        result = await SearchConversationsTool().call(ctx, query="test")
    assert "Error: search failed with status 500" in result


async def test_search_call_no_results() -> None:
    ctx = _make_ctx(nether_api_base_url="http://localhost:9001", nether_auth_token="tok")
    json_data = {"conversations": [], "total": 0, "has_more": False}
    with _patch_client(_mock_response(200, json_data)):
        result = await SearchConversationsTool().call(ctx, query="nothing")
    assert "No conversations found" in result


# ---------------------------------------------------------------------------
# SummarizeConversationTool.call
# ---------------------------------------------------------------------------


async def test_summarize_call_success_current() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="tok",
        nether_conversation_id="conv-1",
    )
    json_data = {"conversation_id": "conv-1", "summary": "A great discussion about AI."}
    with _patch_client(_mock_response(200, json_data), method="post"):
        result = await SummarizeConversationTool().call(ctx)
    assert "Summary generated: A great discussion about AI." in result


async def test_summarize_call_success_explicit_id() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="tok",
        nether_conversation_id="conv-1",
    )
    json_data = {"conversation_id": "conv-other", "summary": "Other summary."}
    with _patch_client(_mock_response(200, json_data), method="post"):
        result = await SummarizeConversationTool().call(ctx, conversation_id="conv-other")
    assert "Other summary." in result


async def test_summarize_call_no_conversation_id() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="tok",
        nether_conversation_id="",
    )
    result = await SummarizeConversationTool().call(ctx)
    assert "Error: no conversation ID provided" in result


async def test_summarize_call_not_found() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="tok",
        nether_conversation_id="conv-missing",
    )
    with _patch_client(_mock_response(404), method="post"):
        result = await SummarizeConversationTool().call(ctx)
    assert "not found" in result


async def test_summarize_call_no_summary_model() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="tok",
        nether_conversation_id="conv-1",
    )
    with _patch_client(_mock_response(501), method="post"):
        result = await SummarizeConversationTool().call(ctx)
    assert "no summary model configured" in result


async def test_summarize_call_empty_conversation() -> None:
    ctx = _make_ctx(
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="tok",
        nether_conversation_id="conv-1",
    )
    with _patch_client(_mock_response(422), method="post"):
        result = await SummarizeConversationTool().call(ctx)
    assert "no committed sessions" in result


# ---------------------------------------------------------------------------
# resolve_tool_config with extras
# ---------------------------------------------------------------------------


def test_resolve_tool_config_extras_passed_through() -> None:
    from netherbrain.agent_runtime.execution.runtime import resolve_tool_config
    from netherbrain.agent_runtime.models.preset import ToolConfigSpec

    spec = ToolConfigSpec()
    tc = resolve_tool_config(
        spec,
        nether_api_base_url="http://localhost:9001",
        nether_auth_token="secret",
        nether_conversation_id="conv-1",
    )
    assert tc.nether_api_base_url == "http://localhost:9001"
    assert tc.nether_auth_token == "secret"  # noqa: S105
    assert tc.nether_conversation_id == "conv-1"


def test_resolve_tool_config_no_extras() -> None:
    from netherbrain.agent_runtime.execution.runtime import resolve_tool_config
    from netherbrain.agent_runtime.models.preset import ToolConfigSpec

    spec = ToolConfigSpec()
    tc = resolve_tool_config(spec)
    assert not hasattr(tc, "nether_api_base_url")
