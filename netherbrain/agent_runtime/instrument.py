"""Langfuse instrumentation and tracing for Netherbrain.

Provides:
- ``pipeline_trace``: Root trace for a session execution.
- ``agent_trace``: Agent span nested under a pipeline trace.
- ``observed_model``: Model wrapper with Langfuse generation spans.
- ``create_model_wrapper``: Factory for SDK ``ModelWrapper`` protocol.
- ``create_global_hooks``: Factory for SDK ``GlobalHooks`` (tool tracing).

Trace hierarchy (Langfuse observation types)::

    Pipeline (as_type="span", set as current)
        +-- Agent (as_type="agent", set as current)
              +-- Generation (as_type="generation", LLM request)
              +-- Tool (as_type="tool", tool call)
              +-- Generation (as_type="generation", LLM stream)
              +-- Tool (as_type="tool", tool call)

Gracefully degrades when Langfuse is not configured or unreachable.
All functions become no-ops; core execution is never affected.
"""

from __future__ import annotations

import logging
import os

# Set environment variables BEFORE importing langfuse.
# Langfuse reads these at import / initialization time.
os.environ.setdefault("OTEL_SERVICE_NAME", "netherbrain")
os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", os.environ.get("NETHER_ENVIRONMENT", "dev"))

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, contextmanager
from functools import wraps
from inspect import signature
from typing import TYPE_CHECKING, Any

from langfuse import get_client
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model, StreamedResponse
from ya_agent_sdk.toolsets.core.base import GlobalHooks

from netherbrain.agent_runtime.costs import calc_price

if TYPE_CHECKING:
    from langfuse import LangfuseAgent, LangfuseSpan, LangfuseTool

logger = logging.getLogger(__name__)

# Suppress noisy langfuse debug logs
logging.getLogger("langfuse").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Client initialization with graceful degradation
# ---------------------------------------------------------------------------

_langfuse_available = False
try:
    if get_client().auth_check():
        _langfuse_available = True
    else:
        os.environ.pop("LANGFUSE_SECRET_KEY", None)
        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_HOST", None)
except Exception:
    logger.warning("Langfuse is not available, tracing disabled")
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_HOST", None)

langfuse = get_client()


def is_langfuse_available() -> bool:
    """Check if Langfuse is available and configured."""
    return _langfuse_available


# ---------------------------------------------------------------------------
# No-op helpers
# ---------------------------------------------------------------------------


@contextmanager
def _noop_observation():
    """No-op context manager when Langfuse is unavailable."""

    class _Noop:
        def update(self, **kwargs: Any) -> None:
            pass

    yield _Noop()


# ---------------------------------------------------------------------------
# Pipeline Trace (root)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def pipeline_trace(
    session_id: str,
    preset: str,
    model: str,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[LangfuseSpan | None]:
    """Create root pipeline trace in Langfuse.

    This is the outermost observation for a session execution.  Sets itself
    as the *current* observation so that all children (agent, generation,
    tool spans) auto-nest under this trace via context propagation.

    Yields ``None`` when Langfuse is unavailable.
    """
    if _langfuse_available:
        with langfuse.start_as_current_observation(
            name="pipeline",
            as_type="span",
            input={"preset": preset, "model": model, "session_id": session_id},
            metadata=metadata or {},
        ) as obs:
            yield obs
    else:
        yield None


# ---------------------------------------------------------------------------
# Agent Trace (nested under pipeline)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def agent_trace(
    agent_name: str,
    model: str | None = None,
) -> AsyncIterator[LangfuseAgent | None]:
    """Create agent observation nested under the current pipeline trace.

    Uses ``as_type="agent"`` and sets itself as the *current* observation
    so that generation and tool spans auto-nest underneath.
    Nesting under the pipeline trace is automatic via context propagation
    (requires ``pipeline_trace`` to be active as the current observation).

    Yields ``None`` when Langfuse is unavailable.
    """
    if _langfuse_available:
        with langfuse.start_as_current_observation(
            name=f"agent:{agent_name}",
            as_type="agent",
            input={"agent_name": agent_name, "model": model},
        ) as obs:
            yield obs
    else:
        yield None


# ---------------------------------------------------------------------------
# Observed Model (wraps request + request_stream)
# ---------------------------------------------------------------------------


def _wrap_model_request(model: Model, agent_name: str) -> Model:
    """Wrap ``model.request`` with a Langfuse generation span."""
    origin_request = model.request
    sig = signature(origin_request)

    @wraps(origin_request)
    async def _wrapped(*args: Any, **kwargs: Any) -> ModelResponse:
        bound_args = sig.bind(*args, **kwargs)
        bound_kwargs = dict(bound_args.arguments)

        if _langfuse_available:
            observation_ctx = langfuse.start_as_current_observation(
                name=f"{agent_name}-llm-request",
                as_type="generation",
            )
        else:
            observation_ctx = _noop_observation()

        with observation_ctx as observation:
            observation.update(
                input={
                    "messages": bound_kwargs["messages"],
                    "model_request_parameters": bound_kwargs.get("model_request_parameters"),
                },
                model=model.model_name,
                model_parameters=bound_kwargs.get("model_settings"),
            )

            response = await origin_request(*args, **kwargs)

            usage_details, cost_details = calc_price(response.usage, model.model_name)
            observation.update(
                output=response.parts,
                usage_details=dict(usage_details) if usage_details else None,  # type: ignore[arg-type]
                cost_details=dict(cost_details) if cost_details else None,  # type: ignore[arg-type]
            )

            return response

    model.request = _wrapped  # type: ignore[assignment]
    return model


def _wrap_model_request_stream(model: Model, agent_name: str) -> Model:
    """Wrap ``model.request_stream`` with a Langfuse generation span."""
    origin_request_stream = model.request_stream
    sig = signature(origin_request_stream)

    @wraps(origin_request_stream)
    @asynccontextmanager
    async def _wrapped(*args: Any, **kwargs: Any) -> AsyncIterator[StreamedResponse]:
        bound_args = sig.bind(*args, **kwargs)
        bound_kwargs = dict(bound_args.arguments)

        if _langfuse_available:
            observation_ctx = langfuse.start_as_current_observation(
                name=f"{agent_name}-llm-stream",
                as_type="generation",
            )
        else:
            observation_ctx = _noop_observation()

        final_response = None
        usage: Any | None = None

        with observation_ctx as observation:
            observation.update(
                input={
                    "messages": bound_kwargs["messages"],
                    "model_request_parameters": bound_kwargs.get("model_request_parameters"),
                },
                model=model.model_name,
                model_parameters=bound_kwargs.get("model_settings"),
            )

            async with origin_request_stream(*args, **kwargs) as streamed_response:
                yield streamed_response

                usage = streamed_response.usage()
                final_response = streamed_response.get()

            usage_details, cost_details = calc_price(usage, model.model_name)
            observation.update(
                output=final_response.parts if final_response else None,
                usage_details=dict(usage_details) if usage_details else None,  # type: ignore[arg-type]
                cost_details=dict(cost_details) if cost_details else None,  # type: ignore[arg-type]
            )

    model.request_stream = _wrapped  # type: ignore[assignment]
    return model


def observed_model(model: Model, agent_name: str) -> Model:
    """Wrap a pydantic-ai Model with Langfuse generation spans.

    Wraps both ``request`` and ``request_stream`` to create Langfuse
    generation observations with token usage and cost details.

    Always wraps (even when Langfuse is unavailable) so that the code
    path is consistent; the no-op context manager ensures zero overhead.
    """
    model = _wrap_model_request(model, agent_name)
    model = _wrap_model_request_stream(model, agent_name)
    return model


# ---------------------------------------------------------------------------
# Tool GlobalHooks (traces tool calls)
# ---------------------------------------------------------------------------

_MAX_TOOL_OUTPUT_CHARS = 4000
"""Maximum characters for tool result stored in Langfuse."""


def _truncate_result(result: Any) -> str:
    """Truncate tool result string for Langfuse display."""
    text = str(result)
    if len(text) <= _MAX_TOOL_OUTPUT_CHARS:
        return text
    return text[:_MAX_TOOL_OUTPUT_CHARS] + f"... [truncated {len(text) - _MAX_TOOL_OUTPUT_CHARS} chars]"


def create_global_hooks() -> GlobalHooks | None:
    """Create ``GlobalHooks`` for tracing tool calls in Langfuse.

    The pre-hook opens a ``tool`` observation with input arguments; the
    post-hook updates the observation with the result and closes it.
    The shared ``metadata`` dict carries the observation reference between hooks.

    Tool observations auto-nest under the current ``agent`` observation
    via Langfuse context propagation (requires ``agent_trace`` to be active).

    Returns ``None`` when Langfuse is unavailable so the caller can
    skip passing hooks entirely (zero overhead).
    """
    if not _langfuse_available:
        return None

    async def _pre_hook(
        ctx: Any,
        tool_name: str,
        tool_args: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            obs = langfuse.start_observation(
                name=tool_name,
                as_type="tool",
                input=tool_args,
                metadata={"tool_name": tool_name},
            )
            metadata["_lf_tool_obs"] = obs
        except Exception:
            logger.debug("Failed to create Langfuse tool observation for %s", tool_name, exc_info=True)
        return tool_args

    async def _post_hook(
        ctx: Any,
        tool_name: str,
        result: Any,
        metadata: dict[str, Any],
    ) -> Any:
        obs: LangfuseTool | None = metadata.pop("_lf_tool_obs", None)
        if obs is not None:
            try:
                is_error = isinstance(result, BaseException)
                obs.update(
                    output=_truncate_result(result),
                    level="ERROR" if is_error else "DEFAULT",
                    status_message="error" if is_error else "success",
                )
                obs.end()
            except Exception:
                logger.debug("Failed to finalize Langfuse tool observation for %s", tool_name, exc_info=True)
        return result

    return GlobalHooks(pre=_pre_hook, post=_post_hook)


# ---------------------------------------------------------------------------
# Subagent execution wrapper (agent-level observation)
# ---------------------------------------------------------------------------


def create_subagent_wrapper() -> Callable[[str, str, dict[str, Any]], AbstractAsyncContextManager[None]] | None:
    """Create a subagent execution wrapper for Langfuse agent observations.

    The wrapper creates an ``agent`` observation around the entire subagent
    execution.  Since it uses ``start_as_current_observation``, all child
    observations (generation spans from ``model_wrapper``, tool observations
    from ``global_hooks``) auto-nest underneath.

    Returns ``None`` when Langfuse is unavailable (zero overhead).
    """
    if not _langfuse_available:
        return None

    @asynccontextmanager
    async def wrapper(agent_name: str, agent_id: str, metadata: dict[str, Any]):
        with langfuse.start_as_current_observation(
            name=f"agent:{agent_name}",
            as_type="agent",
            input={"agent_name": agent_name, "agent_id": agent_id},
        ):
            yield

    return wrapper


# ---------------------------------------------------------------------------
# SDK ModelWrapper factory
# ---------------------------------------------------------------------------


def create_model_wrapper() -> Callable[[Model, str, dict[str, Any]], Model]:
    """Create a model wrapper function for SDK integration.

    The returned wrapper follows the SDK's ``ModelWrapper`` protocol::

        Callable[[Model, str, dict[str, Any]], Model]

    This enables automatic instrumentation of all models created by the
    SDK: main agent, subagents, image/video understanding, etc.
    """

    def wrapper(model: Model, agent_name: str, metadata: dict[str, Any]) -> Model:
        return observed_model(model, agent_name)

    return wrapper


__all__ = [
    "agent_trace",
    "create_global_hooks",
    "create_model_wrapper",
    "create_subagent_wrapper",
    "is_langfuse_available",
    "observed_model",
    "pipeline_trace",
]
