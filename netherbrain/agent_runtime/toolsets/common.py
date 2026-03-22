"""Shared helpers for Netherbrain toolsets that call the runtime's own API.

All Netherbrain-specific tools (history, control) communicate with the
agent-runtime via its REST API, authenticated using a session-scoped JWT
injected through ``ToolConfig`` extras by ``create_service_runtime``.
The JWT carries the caller's user identity so that API calls are properly
scoped (e.g. ``search_conversations`` only returns the user's data).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from ya_agent_sdk.context import AgentContext


def get_nether_config(ctx: RunContext[AgentContext]) -> tuple[str, str, str]:
    """Extract Netherbrain API config from ToolConfig extras.

    Returns
    -------
    tuple of (api_base_url, auth_token, conversation_id)
        ``api_base_url`` and ``auth_token`` are always present when the
        tool is available (``is_available`` checks ``api_base_url``).
        ``conversation_id`` may be empty for session-level tools.
    """
    tc = ctx.deps.tool_config
    api_base_url: str = getattr(tc, "nether_api_base_url", "")
    auth_token: str = getattr(tc, "nether_auth_token", "")
    conversation_id: str = getattr(tc, "nether_conversation_id", "")
    return api_base_url, auth_token, conversation_id


def is_nether_api_available(ctx: RunContext[AgentContext]) -> bool:
    """Check if the Netherbrain API is configured."""
    tc = ctx.deps.tool_config
    return bool(getattr(tc, "nether_api_base_url", ""))


def build_client(api_base_url: str, auth_token: str) -> httpx.AsyncClient:
    """Build an httpx async client with Netherbrain auth headers."""
    return httpx.AsyncClient(
        base_url=api_base_url,
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,
    )
