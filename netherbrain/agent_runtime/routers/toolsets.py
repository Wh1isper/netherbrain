"""GET /api/toolsets -- capability discovery endpoint.

Returns the list of available toolsets and their constituent tools.
This is a pure read endpoint that reflects the server's built-in
toolset registry; no database access is required.
"""

from __future__ import annotations

from fastapi import APIRouter

from netherbrain.agent_runtime.execution.runtime import (
    _CORE_TOOLSETS,
    TOOLSET_REGISTRY,
)
from netherbrain.agent_runtime.models.api import ToolsetInfo

router = APIRouter(prefix="/toolsets", tags=["toolsets"])

# Human-readable descriptions for each toolset.
_DESCRIPTIONS: dict[str, str] = {
    "content": "Media content loading (images, URLs).",
    "context": "Context management (handoff).",
    "document": "Document conversion (PDF, Office).",
    "enhance": "Task tracking and workflow enhancement tools.",
    "filesystem": "File and directory operations (read, write, edit, search).",
    "multimodal": "Image and video understanding.",
    "shell": "Shell command execution.",
    "web": "Web search, scraping, and file download.",
    "core": "Alias that enables all built-in toolsets.",
    "history": "Conversation history search and summarization (main agent only, not inherited by subagents).",
    "control": "Session control tools: steer running agent sessions (main agent only, not inherited by subagents).",
}


def _build_toolset_list() -> list[ToolsetInfo]:
    result: list[ToolsetInfo] = []

    # Individual toolsets from registry.
    for name, tools in TOOLSET_REGISTRY.items():
        result.append(
            ToolsetInfo(
                name=name,
                description=_DESCRIPTIONS.get(name, ""),
                tools=[t.name for t in tools],
                is_alias=False,
            )
        )

    # "core" alias -- expands to all standard toolsets.
    core_tools: list[str] = []
    for ts_name in _CORE_TOOLSETS:
        tools = TOOLSET_REGISTRY.get(ts_name, [])
        core_tools.extend(t.name for t in tools)

    result.append(
        ToolsetInfo(
            name="core",
            description=_DESCRIPTIONS["core"],
            tools=core_tools,
            is_alias=True,
        )
    )

    return result


# Pre-build at import time (registry is static after startup).
_TOOLSET_LIST: list[ToolsetInfo] = _build_toolset_list()


@router.get("", response_model=list[ToolsetInfo])
async def handle_list_toolsets() -> list[ToolsetInfo]:
    """Return all available toolsets and their tools."""
    return _TOOLSET_LIST
