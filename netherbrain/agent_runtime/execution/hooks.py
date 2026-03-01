"""Hook management for stream_agent integration.

Provides ``UsageSnapshotEmitter`` which injects ``UsageSnapshot`` events
with real token usage data into the SDK's output queue after each model
request completes.

Usage::

    emitter = UsageSnapshotEmitter(session_id="sess-123", model_id="anthropic:claude-sonnet-4")

    async with stream_agent(
        runtime,
        post_node_hook=emitter.post_node_hook,
    ) as streamer:
        async for event in streamer:
            ...
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ya_agent_sdk.context import StreamEvent

from netherbrain.agent_runtime.execution.events import (
    MAIN_AGENT_ID,
    PipelineUsage,
    UsageSnapshot,
)

if TYPE_CHECKING:
    from ya_agent_sdk.agents.main import NodeHookContext

logger = logging.getLogger(__name__)


class UsageSnapshotEmitter:
    """Emits ``UsageSnapshot`` events after each model request.

    Reads real token usage from ``ctx.run.usage()`` and injects
    a ``UsageSnapshot`` into the output queue as a ``StreamEvent``.
    The protocol adapter then converts it to an AG-UI ``CustomEvent``.

    Note: During streaming, only main-model usage is available from
    ``ctx.run.usage()``.  Extra usages (subagents, compact, etc.) are
    only available at run completion via ``runtime.ctx.extra_usages``.
    """

    def __init__(self, session_id: str, model_id: str) -> None:
        self._session_id = session_id
        self._model_id = model_id

    async def post_node_hook(self, ctx: NodeHookContext[Any, Any]) -> None:
        """Inject ``UsageSnapshot`` with real usage into output queue."""
        if ctx.run is None:
            return

        try:
            sdk_usage = ctx.run.usage()
            usage = PipelineUsage.from_run_usage(self._model_id, sdk_usage)
        except Exception:
            logger.debug("Could not extract usage from run", exc_info=True)
            return

        event = UsageSnapshot(
            event_id=self._session_id,
            session_id=self._session_id,
            usage=usage,
        )
        await ctx.output_queue.put(
            StreamEvent(
                agent_id=MAIN_AGENT_ID,
                agent_name=MAIN_AGENT_ID,
                event=event,
            )
        )
