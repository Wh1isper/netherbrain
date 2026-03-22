"""Spawn delegate tool -- enables parent agents to spawn async subagents.

Creates a pydantic-ai ``Tool`` as a closure over runtime infrastructure.
The tool is injected into the agent when ``SubagentSpec.async_enabled``
is True.

Dependency injection strategy: infrastructure references are bundled in
``DelegateContext`` and stored in ``AgentContext.metadata['delegate_ctx']``.
The tool function reads this context at invocation time.

Subagent sessions are launched through ``ExecutionManager.execute_session()``
-- the same code path used by the REST API -- rather than calling
``launch_session()`` directly.  This ensures consistent validation,
config resolution, and session lifecycle management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext, Tool

from netherbrain.agent_runtime.models.enums import EnvironmentMode, InputPartType, SessionType, Transport
from netherbrain.agent_runtime.models.input import InputPart
from netherbrain.agent_runtime.models.preset import SubagentRef

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from netherbrain.agent_runtime.managers.execution import ExecutionManager

logger = logging.getLogger(__name__)


@dataclass
class DelegateContext:
    """Infrastructure context for the spawn_delegate tool.

    Bundled into ``AgentContext.metadata`` so the tool closure can access
    runtime services without global state.

    The ``async_subagent_registry`` dict is the **same object** referenced
    by ``RuntimeSession.async_subagent_registry``, ensuring the tool's
    writes are visible to the session registry.
    """

    session_id: str
    conversation_id: str
    subagent_refs: list[SubagentRef]
    async_subagent_registry: dict[str, str]

    # ExecutionManager handles config resolution, session creation, and launch.
    execution_manager: ExecutionManager | None
    session_factory: async_sessionmaker

    # Transport for subagent sessions (determined by Redis availability).
    subagent_transport: Transport = Transport.SSE

    # Environment inheritance from parent config.
    parent_project_ids: list[str] = field(default_factory=list)
    parent_environment_mode: EnvironmentMode | None = None
    parent_container_id: str | None = None
    parent_container_workdir: str | None = None
    user_id: str | None = None


def _find_ref(refs: list[SubagentRef], name: str) -> SubagentRef | None:
    """Find a SubagentRef by name (case-sensitive)."""
    for ref in refs:
        if ref.name == name:
            return ref
    return None


def create_spawn_delegate_tool(delegate_ctx: DelegateContext) -> Tool:
    """Create the ``spawn_delegate`` pydantic-ai Tool.

    The returned tool is a closure over ``delegate_ctx`` and resolves
    subagent configs / launches sessions when invoked by the LLM.

    Parameters
    ----------
    delegate_ctx:
        Infrastructure context providing access to execution management
        and subagent definitions.

    Returns
    -------
    Tool
        A pydantic-ai Tool instance ready to be added to the agent.
    """
    available_names = [ref.name for ref in delegate_ctx.subagent_refs]
    names_doc = ", ".join(f"'{n}'" for n in available_names) if available_names else "(none configured)"

    async def spawn_delegate(ctx: RunContext[Any], name: str, instruction: str) -> str:
        """Spawn a background subagent to work on a task independently.

        The subagent runs in its own session in parallel with the current
        agent. Results are delivered to the conversation mailbox and
        become available when the caller fires a continuation.

        Args:
            name: Subagent name. Available: {names_doc}
            instruction: Task description and context for the subagent.
        """
        dc = delegate_ctx

        if dc.execution_manager is None:
            return "Error: execution manager not available"

        # Validate subagent name.
        ref = _find_ref(dc.subagent_refs, name)
        if ref is None:
            return f"Error: unknown subagent '{name}'. Available: {names_doc}"

        # Build input from instruction (+ optional subagent-ref instruction prefix).
        text = instruction
        if ref.instruction:
            text = f"{ref.instruction}\n\n{instruction}"

        input_parts = [InputPart(type=InputPartType.TEXT, text=text)]

        # Determine parent session for resume (if subagent was previously dispatched).
        parent_session_id = dc.async_subagent_registry.get(name)

        # Launch the subagent session via ExecutionManager (same path as REST API).
        try:
            async with dc.session_factory() as db:
                result = await dc.execution_manager.execute_session(
                    db,
                    preset_id=ref.preset_id,
                    input_parts=input_parts,
                    parent_session_id=parent_session_id,
                    transport=dc.subagent_transport,
                    session_type=SessionType.ASYNC_SUBAGENT,
                    spawned_by=dc.session_id,
                    subagent_name=name,
                    parent_environment_mode=dc.parent_environment_mode,
                    parent_container_id=dc.parent_container_id,
                    parent_container_workdir=dc.parent_container_workdir,
                    user_id=dc.user_id,
                )
        except Exception as exc:
            logger.exception("Failed to launch subagent '%s'", name)
            return f"Error: failed to launch subagent: {exc}"

        # Update registry so subsequent dispatches of the same name can resume.
        dc.async_subagent_registry[name] = result.session_id

        logger.info(
            "Dispatched async subagent '%s': session=%s, conversation=%s",
            name,
            result.session_id,
            result.conversation_id,
        )
        return f"Task dispatched to '{name}' (session: {result.session_id})"

    # Update the docstring with actual available names.
    spawn_delegate.__doc__ = (spawn_delegate.__doc__ or "").replace("{names_doc}", names_doc)

    return Tool(
        function=spawn_delegate,
        name="spawn_delegate",
        description=(
            "Spawn a background subagent to work on a task independently. "
            "The subagent runs in its own session; results are delivered "
            "to the conversation mailbox. "
            f"Available subagents: {names_doc}"
        ),
    )
