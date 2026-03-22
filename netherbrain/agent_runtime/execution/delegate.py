"""Spawn delegate tool -- enables parent agents to spawn async subagents.

Creates a pydantic-ai ``Tool`` as a closure over runtime infrastructure.
The tool is injected into the agent when ``SubagentSpec.async_enabled``
is True.

Dependency injection strategy: infrastructure references are bundled in
``DelegateContext`` and stored in ``AgentContext.metadata['delegate_ctx']``.
The tool function reads this context at invocation time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext, Tool

from netherbrain.agent_runtime.execution.launch import launch_session
from netherbrain.agent_runtime.execution.resolver import resolve_config
from netherbrain.agent_runtime.models.enums import InputPartType, SessionType, Transport
from netherbrain.agent_runtime.models.input import InputPart
from netherbrain.agent_runtime.models.preset import SubagentRef

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from netherbrain.agent_runtime.managers.sessions import SessionManager
    from netherbrain.agent_runtime.registry import SessionRegistry
    from netherbrain.agent_runtime.settings import NetherSettings

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
    session_manager: SessionManager
    registry: SessionRegistry
    settings: NetherSettings
    session_factory: async_sessionmaker
    redis: aioredis.Redis | None = None

    # Resolved configs are cached to avoid repeated DB lookups for the
    # same subagent preset within a single parent execution.
    _config_cache: dict[str, Any] = field(default_factory=dict, repr=False)


def _find_ref(refs: list[SubagentRef], name: str) -> SubagentRef | None:
    """Find a SubagentRef by name (case-sensitive)."""
    for ref in refs:
        if ref.name == name:
            return ref
    return None


async def _load_parent_state(dc: DelegateContext, name: str) -> tuple[str | None, Any]:
    """Load parent state for a subagent from its previous session.

    Returns (parent_session_id, parent_state).  Falls back to (None, None)
    if the parent session cannot be loaded.
    """
    parent_session_id = dc.async_subagent_registry.get(name)
    if not parent_session_id:
        return None, None

    try:
        async with dc.session_factory() as db:
            parent_data = await dc.session_manager.get_session(db, parent_session_id, include_state=True)
            return parent_session_id, parent_data.state
    except Exception:
        logger.warning(
            "Could not load parent state for subagent '%s' (session %s), starting fresh",
            name,
            parent_session_id,
        )
        return None, None


def create_spawn_delegate_tool(delegate_ctx: DelegateContext) -> Tool:
    """Create the ``spawn_delegate`` pydantic-ai Tool.

    The returned tool is a closure over ``delegate_ctx`` and resolves
    subagent configs / launches sessions when invoked by the LLM.

    Parameters
    ----------
    delegate_ctx:
        Infrastructure context providing access to session management,
        registry, and subagent definitions.

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

        # Validate subagent name.
        ref = _find_ref(dc.subagent_refs, name)
        if ref is None:
            return f"Error: unknown subagent '{name}'. Available: {names_doc}"

        # Resolve config for the subagent's preset.
        try:
            if ref.preset_id in dc._config_cache:
                config = dc._config_cache[ref.preset_id]
            else:
                async with dc.session_factory() as db:
                    config = await resolve_config(db, preset_id=ref.preset_id)
                dc._config_cache[ref.preset_id] = config
        except Exception as exc:
            logger.exception("Failed to resolve config for subagent '%s'", name)
            return f"Error: failed to resolve subagent config: {exc}"

        # Determine parent session for resume (if subagent was previously dispatched).
        parent_session_id, parent_state = await _load_parent_state(dc, name)

        # Build input from instruction (+ optional subagent-ref instruction prefix).
        text = instruction
        if ref.instruction:
            text = f"{ref.instruction}\n\n{instruction}"

        input_parts = [InputPart(type=InputPartType.TEXT, text=text)]

        # Launch the subagent session in background.
        try:
            async with dc.session_factory() as db:
                result = await launch_session(
                    db=db,
                    session_factory=dc.session_factory,
                    session_manager=dc.session_manager,
                    registry=dc.registry,
                    settings=dc.settings,
                    redis=dc.redis,
                    config=config,
                    input_parts=input_parts,
                    transport=Transport.STREAM if dc.redis else Transport.SSE,
                    parent_session_id=parent_session_id,
                    parent_state=parent_state,
                    conversation_id=dc.conversation_id,
                    session_type=SessionType.ASYNC_SUBAGENT,
                    spawned_by=dc.session_id,
                    subagent_name=name,
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
