"""External tools meta tool -- enables callers to inject HTTP callback tools.

Creates a pydantic-ai ``Tool`` (``call_external``) as a closure over caller-
provided tool specs.  The agent sees a single tool with a dynamically-built
description listing every registered external tool, its purpose, and its
parameter schema.

At invocation time the meta tool:

1. Resolves the requested tool name.
2. Validates arguments against the stored JSON Schema.
3. Proxies the HTTP request to the callback URL via httpx.
4. Returns the response body (or an error string) to the agent.

External tool specs are ephemeral -- passed per-request, never persisted.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import ValidationError, create_model
from pydantic_ai import RunContext, Tool

if TYPE_CHECKING:
    from netherbrain.agent_runtime.models.api import ExternalToolSpec

logger = logging.getLogger(__name__)

# JSON Schema type -> Python type mapping for dynamic Pydantic models.
_JSON_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _build_pydantic_model(schema: dict) -> type | None:
    """Build a dynamic Pydantic model from a JSON Schema object definition.

    Handles flat object schemas with typed properties.  Returns ``None``
    when the schema has no ``properties`` (nothing to validate).
    """
    properties = schema.get("properties")
    if not properties:
        return None

    required = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for name, prop in properties.items():
        python_type = _JSON_SCHEMA_TYPE_MAP.get(prop.get("type", ""), Any)
        if name in required:
            fields[name] = (python_type, ...)
        else:
            fields[name] = (python_type | None, None)

    return create_model("ExternalToolArgs", **fields)


def _validate_arguments(arguments: dict, schema: dict) -> str | None:
    """Validate *arguments* against a JSON Schema using a dynamic Pydantic model.

    Returns an error message string if validation fails, or ``None`` if
    arguments are valid.  If the schema itself is malformed, validation is
    skipped with a warning (we do not trust external schemas to be correct).
    """
    if not schema:
        return None

    try:
        model = _build_pydantic_model(schema)
    except Exception:
        logger.warning("Failed to build validation model from schema, skipping validation", exc_info=True)
        return None

    if model is None:
        return None

    try:
        model.model_validate(arguments)
    except ValidationError as exc:
        return f"Argument validation failed: {exc}"

    return None


# ---------------------------------------------------------------------------
# Description builder
# ---------------------------------------------------------------------------


def _build_description(specs: Sequence[ExternalToolSpec]) -> str:
    """Build a dynamic description listing all registered external tools."""
    lines = [
        "Call an external tool by name. Available tools:",
        "",
    ]
    for spec in specs:
        lines.append(f"- **{spec.name}**: {spec.description}")
        if spec.parameters_schema:
            # Compact JSON Schema summary for the model.
            schema_str = json.dumps(spec.parameters_schema, indent=2)
            lines.append(f"  Parameters: {schema_str}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP proxy
# ---------------------------------------------------------------------------


async def _execute_http_call(spec: ExternalToolSpec, arguments: dict) -> str:
    """Execute the HTTP callback and return the response body."""
    async with httpx.AsyncClient(timeout=spec.timeout) as client:
        response = await client.request(
            method=spec.method.upper(),
            url=spec.url,
            headers=spec.headers,
            json=arguments,
        )

    # Return body as string.  Include status on non-2xx for agent awareness.
    body = response.text
    if response.is_success:
        return body or "(empty response)"

    return f"HTTP {response.status_code}: {body}"


# ---------------------------------------------------------------------------
# Meta tool factory
# ---------------------------------------------------------------------------


def create_external_meta_tool(specs: Sequence[ExternalToolSpec]) -> Tool:
    """Create the ``call_external`` pydantic-ai Tool.

    The returned tool is a closure over the provided ``ExternalToolSpec``
    list.  It resolves tool names, validates arguments, and proxies HTTP
    requests at invocation time.

    Parameters
    ----------
    specs:
        External tool definitions provided by the session caller.

    Returns
    -------
    Tool
        A pydantic-ai Tool instance ready to be added to the agent.
    """
    # Build lookup map for O(1) resolution.
    tool_map: dict[str, ExternalToolSpec] = {spec.name: spec for spec in specs}
    available_names = list(tool_map.keys())
    names_doc = ", ".join(f"'{n}'" for n in available_names)

    async def call_external(ctx: RunContext[Any], tool_name: str, arguments: dict) -> str:
        """Call an external tool by name with the given arguments.

        Args:
            tool_name: Name of the external tool to invoke. Available: {names_doc}
            arguments: Arguments dict matching the tool's parameter schema.
        """
        # Resolve tool name.
        spec = tool_map.get(tool_name)
        if spec is None:
            return f"Error: unknown tool '{tool_name}'. Available: {names_doc}"

        # Validate arguments against schema.
        validation_error = _validate_arguments(arguments, spec.parameters_schema)
        if validation_error is not None:
            return f"Error: {validation_error}"

        # Execute HTTP callback.
        try:
            return await _execute_http_call(spec, arguments)
        except httpx.TimeoutException:
            logger.warning("External tool '%s' timed out (url=%s)", tool_name, spec.url)
            return f"Error: request to '{tool_name}' timed out after {spec.timeout}s"
        except httpx.RequestError as exc:
            logger.warning("External tool '%s' request failed: %s", tool_name, exc)
            return f"Error: request to '{tool_name}' failed: {exc}"
        except Exception as exc:
            logger.exception("Unexpected error calling external tool '%s'", tool_name)
            return f"Error: unexpected error calling '{tool_name}': {exc}"

    # Inject available names into docstring.
    call_external.__doc__ = (call_external.__doc__ or "").replace("{names_doc}", names_doc)

    description = _build_description(specs)

    return Tool(
        function=call_external,
        name="call_external",
        description=description,
    )
