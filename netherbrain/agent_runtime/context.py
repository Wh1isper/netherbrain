"""Runtime session context.

Wraps the ya-agent-sdk AgentContext with runtime-specific state needed by the
execution coordinator, event processor, and session registry.

Design note: pydantic-ai uses ``RunContext[AgentContext]`` as the dependency
type for tools.  We do NOT subclass AgentContext here because ``create_agent``
constructs it internally.  Instead we use composition -- ``RuntimeSession``
holds the SDK context alongside runtime bookkeeping fields.  When the
execution layer needs to expose runtime data to custom tools, it can attach
extra info via the SDK context's metadata or a dedicated side-channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from netherbrain.agent_runtime.models.enums import SessionType, Transport

if TYPE_CHECKING:
    pass  # Future: AgentContext, AgentStreamer, EventProcessor, ...


@dataclass
class RuntimeSession:
    """In-flight state for a single agent execution.

    Created by the execution coordinator at run start; registered in the
    SessionRegistry for interrupt / steering; discarded after commit.
    """

    # -- Identity --------------------------------------------------------------
    session_id: str
    conversation_id: str
    parent_session_id: str | None = None
    preset_id: str | None = None

    # -- Classification --------------------------------------------------------
    session_type: SessionType = SessionType.AGENT
    transport: Transport = Transport.SSE

    # -- Live references (set during execution) --------------------------------
    # These will be typed properly when the execution layer is implemented.
    sdk_context: Any = None  # AgentContext from ya-agent-sdk
    streamer: Any = None  # AgentStreamer -- live handle for interrupt
    event_processor: Any = None  # EventProcessor instance

    # -- Async subagent tracking -----------------------------------------------
    async_subagent_registry: dict[str, str] = field(default_factory=dict)
    """Map of subagent_name -> session_id for dispatched async subagents."""

    # -- Transport info --------------------------------------------------------
    stream_key: str | None = None
    """Redis stream key (only when transport=stream)."""
