"""Internal pipeline events emitted by the execution coordinator.

These extend ``AgentEvent`` from ya-agent-sdk and represent pipeline-level
milestones that are invisible to external consumers.  They are consumed by
the protocol adapter (``streaming.protocols``) which converts them to the
external protocol (AG-UI ``ProtocolEvent``).

These events exist at the same abstraction level as SDK sideband events
(SubagentStartEvent, CompactStartEvent, etc.) but originate from the
Netherbrain coordinator rather than the SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ya_agent_sdk.events import AgentEvent

if TYPE_CHECKING:
    from pydantic_ai.usage import RunUsage

# Magic constant for the main agent identifier in StreamEvent.
MAIN_AGENT_ID = "main"


# ---------------------------------------------------------------------------
# Usage data (shared across events)
# ---------------------------------------------------------------------------


@dataclass
class ModelUsage:
    """Token usage for a single model.

    Fields aligned with ``pydantic_ai.RunUsage`` naming conventions.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0

    def __add__(self, other: ModelUsage) -> ModelUsage:
        return ModelUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            requests=self.requests + other.requests,
        )

    @classmethod
    def from_run_usage(cls, sdk_usage: RunUsage) -> ModelUsage:
        """Create from ``pydantic_ai.RunUsage``."""
        return cls(
            input_tokens=sdk_usage.input_tokens,
            output_tokens=sdk_usage.output_tokens,
            cache_read_tokens=sdk_usage.cache_read_tokens,
            cache_write_tokens=sdk_usage.cache_write_tokens,
            reasoning_tokens=sdk_usage.details.get("reasoning_tokens", 0),
            total_tokens=sdk_usage.input_tokens + sdk_usage.output_tokens,
            requests=sdk_usage.requests,
        )


@dataclass
class PipelineUsage:
    """Aggregated token usage by model_id.

    Different models have different costs, so usage is tracked per model.
    The ``total`` property provides a convenience aggregate across all models.
    """

    model_usages: dict[str, ModelUsage] = field(default_factory=dict)

    def add(self, model_id: str, usage: ModelUsage) -> None:
        """Accumulate usage for a model."""
        if model_id in self.model_usages:
            self.model_usages[model_id] = self.model_usages[model_id] + usage
        else:
            self.model_usages[model_id] = usage

    @property
    def total(self) -> ModelUsage:
        """Aggregate usage across all models."""
        result = ModelUsage()
        for usage in self.model_usages.values():
            result = result + usage
        return result

    @classmethod
    def from_run_usage(cls, model_id: str, sdk_usage: RunUsage) -> PipelineUsage:
        """Create from a single model's ``RunUsage``."""
        result = cls()
        result.add(model_id, ModelUsage.from_run_usage(sdk_usage))
        return result


# ---------------------------------------------------------------------------
# Pipeline lifecycle events
# ---------------------------------------------------------------------------


@dataclass
class PipelineStarted(AgentEvent):
    """Emitted when a session execution begins.

    Produced before the SDK ``stream_agent`` call.
    """

    session_id: str = ""
    conversation_id: str = ""


@dataclass
class PipelineCompleted(AgentEvent):
    """Emitted when a session execution completes successfully.

    Produced after the SDK streamer is fully consumed and state
    has been exported.
    """

    session_id: str = ""
    reply: str | None = None
    usage: PipelineUsage = field(default_factory=PipelineUsage)


@dataclass
class PipelineFailed(AgentEvent):
    """Emitted when a session execution fails.

    Produced when an unrecoverable error occurs during execution.
    """

    session_id: str = ""
    error: str = ""
    error_type: str = "execution_error"


@dataclass
class UsageSnapshot(AgentEvent):
    """Periodic token usage update during execution.

    Produced after each model request completes to provide
    incremental usage visibility.
    """

    session_id: str = ""
    usage: PipelineUsage = field(default_factory=PipelineUsage)
