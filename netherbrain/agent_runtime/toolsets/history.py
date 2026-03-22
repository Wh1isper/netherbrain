"""Conversation history tools -- search and summarize via HTTP API.

Provides ``BaseTool`` subclasses for searching past conversations and
generating LLM summaries.  Tools communicate with the agent-runtime's
own REST API using httpx, authenticated via the root auth token.

These tools have ``auto_inherit = False`` (the default), so they are NOT
inherited by sync subagents.  They are also excluded from async subagent
sessions by the coordinator (only injected when ``subagent_name is None``).

Configuration is read from ``ToolConfig`` extras injected by the runtime
factory (``create_service_runtime``):

- ``nether_api_base_url``: Base URL for the agent-runtime API.
- ``nether_auth_token``: Root auth token for API access.
- ``nether_conversation_id``: Current conversation ID (default for summarize).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext
from ya_agent_sdk.context import AgentContext
from ya_agent_sdk.toolsets.core.base import BaseTool

from netherbrain.agent_runtime.toolsets.common import build_client, get_nether_config, is_nether_api_available

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def format_search_results(data: dict[str, Any], query: str) -> str:
    """Format search API response into a human-readable string.

    Extracted for testability (no HTTP, no LLM).
    """
    conversations = data.get("conversations", [])
    total = data.get("total", 0)

    if not conversations:
        return f"No conversations found matching '{query}'."

    lines = [f"Found {total} conversation(s) matching '{query}':"]
    for conv in conversations:
        label = conv.get("summary") or conv.get("title") or "(untitled)"
        cid = conv["conversation_id"]
        match = conv.get("match_source", "unknown")
        lines.append(f"- [{cid}] {label} (matched in: {match})")

    if data.get("has_more"):
        lines.append(f"... and {total - len(conversations)} more.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SearchConversationsTool(BaseTool):
    """Search past conversation history by keyword."""

    name = "search_conversations"
    description = (
        "Search past conversation history by keyword. "
        "Finds conversations matching the query across titles, summaries, and message content."
    )
    # auto_inherit = False (default) -- not inherited by subagents

    def is_available(self, ctx: RunContext[AgentContext]) -> bool:
        """Available when the Netherbrain API base URL is configured."""
        return is_nether_api_available(ctx)

    async def call(
        self,
        ctx: RunContext[AgentContext],
        query: Annotated[str, Field(description="Search keywords (space-separated, AND semantics)")],
        limit: Annotated[
            int,
            Field(description="Maximum number of results (1-50)", default=10, ge=1, le=50),
        ] = 10,
    ) -> str:
        """Search conversations via the agent-runtime REST API."""
        api_base_url, auth_token, _ = get_nether_config(ctx)

        async with build_client(api_base_url, auth_token) as client:
            resp = await client.get(
                "/api/conversations/search",
                params={"q": query, "limit": limit},
            )

        if resp.status_code != 200:
            return f"Error: search failed with status {resp.status_code}."

        return format_search_results(resp.json(), query)


class SummarizeConversationTool(BaseTool):
    """Generate or update an LLM-powered summary for a conversation."""

    name = "summarize_conversation"
    description = (
        "Generate an LLM-powered summary for a conversation. "
        "Defaults to the current conversation if no ID is specified."
    )

    def is_available(self, ctx: RunContext[AgentContext]) -> bool:
        """Available when the Netherbrain API base URL is configured."""
        return is_nether_api_available(ctx)

    async def call(
        self,
        ctx: RunContext[AgentContext],
        conversation_id: Annotated[
            str,
            Field(
                description="Conversation ID to summarize. Leave empty for current conversation.",
                default="",
            ),
        ] = "",
    ) -> str:
        """Summarize a conversation via the agent-runtime REST API."""
        api_base_url, auth_token, current_cid = get_nether_config(ctx)
        target_id = conversation_id or current_cid

        if not target_id:
            return "Error: no conversation ID provided and current conversation unknown."

        async with build_client(api_base_url, auth_token) as client:
            resp = await client.post(f"/api/conversations/{target_id}/summarize")

        if resp.status_code == 404:
            return f"Error: conversation '{target_id}' not found."
        if resp.status_code == 501:
            return "Error: no summary model configured (NETHER_SUMMARY_MODEL is not set)."
        if resp.status_code == 422:
            return "Error: conversation has no committed sessions to summarize."
        if resp.status_code != 200:
            return f"Error: summarize failed with status {resp.status_code}."

        data = resp.json()
        summary = data.get("summary", "")
        return f"Summary generated: {summary}"


# ---------------------------------------------------------------------------
# Registry export
# ---------------------------------------------------------------------------

tools: list[type[BaseTool]] = [SearchConversationsTool, SummarizeConversationTool]
