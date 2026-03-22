"""Session control tools -- steer running agent sessions via HTTP API.

Provides ``BaseTool`` subclasses for controlling active sessions.
Tools communicate with the agent-runtime's own REST API using httpx,
authenticated via the root auth token.

These tools have ``auto_inherit = False`` (the default), so they are NOT
inherited by sync subagents.  They are also excluded from async subagent
sessions by the coordinator (only injected when ``subagent_name is None``).
"""

from __future__ import annotations

import logging
from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext
from ya_agent_sdk.context import AgentContext
from ya_agent_sdk.toolsets.core.base import BaseTool

from netherbrain.agent_runtime.toolsets.common import build_client, get_nether_config, is_nether_api_available

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SteerAgentTool(BaseTool):
    """Send steering guidance to a running agent session."""

    name = "steer_agent"
    description = (
        "Send guidance to a running agent session by session ID. "
        "The message is injected at the agent's next LLM turn boundary "
        "without interrupting its current work. "
        "Use this to provide additional context or redirect a running async subagent."
    )

    def is_available(self, ctx: RunContext[AgentContext]) -> bool:
        """Available when the Netherbrain API base URL is configured."""
        return is_nether_api_available(ctx)

    async def call(
        self,
        ctx: RunContext[AgentContext],
        session_id: Annotated[str, Field(description="Session ID of the running agent to steer")],
        message: Annotated[str, Field(description="Guidance or additional context to send")],
    ) -> str:
        """Steer a running session via the agent-runtime REST API."""
        if not message:
            return "Error: message cannot be empty."

        api_base_url, auth_token, _ = get_nether_config(ctx)

        async with build_client(api_base_url, auth_token) as client:
            resp = await client.post(
                f"/api/sessions/{session_id}/steer",
                json={"input": [{"type": "text", "text": message}]},
            )

        if resp.status_code == 404:
            return f"Session '{session_id}' is not currently running."
        if resp.status_code == 409:
            return f"Session '{session_id}' is still initializing (context not ready)."
        if resp.status_code == 422:
            return "Error: steering message cannot be empty."
        if resp.status_code != 200:
            return f"Error: steer failed with status {resp.status_code}."

        return f"Guidance sent to session '{session_id}'."


# ---------------------------------------------------------------------------
# Registry export
# ---------------------------------------------------------------------------

tools: list[type[BaseTool]] = [SteerAgentTool]
