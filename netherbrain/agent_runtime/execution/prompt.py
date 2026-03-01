"""System prompt rendering with Jinja2 template support.

Preset system prompts may contain Jinja2 template syntax.  This module
renders them with context variables derived from the resolved config
and runtime state.

Template variables available:

- ``project_ids``    : list[str]  -- active project IDs
- ``default_project``: str | None -- first project ID (CWD)
- ``shell_mode``     : str        -- "local" or "docker"
- ``model_name``     : str        -- model identifier
- ``preset_id``      : str        -- active preset ID
- ``date``           : str        -- current date (YYYY-MM-DD)

Example template::

    You are a coding assistant working on {{ default_project }}.
    {% if project_ids | length > 1 %}
    You also have access to: {{ project_ids[1:] | join(', ') }}
    {% endif %}
"""

from __future__ import annotations

from datetime import UTC, datetime

import jinja2

from netherbrain.agent_runtime.execution.resolver import ResolvedConfig


def render_system_prompt(
    config: ResolvedConfig,
    *,
    extra_vars: dict[str, object] | None = None,
) -> str:
    """Render the system prompt template with config-derived variables.

    Parameters
    ----------
    config:
        Fully resolved execution config.
    extra_vars:
        Additional template variables (override defaults on conflict).

    Returns
    -------
    str
        The rendered system prompt.  If the template contains no Jinja2
        syntax, the original string is returned unchanged.
    """
    template_vars: dict[str, object] = {
        "project_ids": config.project_ids,
        "default_project": config.project_ids[0] if config.project_ids else None,
        "shell_mode": config.shell_mode.value,
        "model_name": config.model.name,
        "preset_id": config.preset_id,
        "date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
    }

    if extra_vars:
        template_vars.update(extra_vars)

    # Fast path: skip Jinja2 if no template syntax detected
    raw = config.system_prompt
    if "{{" not in raw and "{%" not in raw:
        return raw

    env = jinja2.Environment(autoescape=False)  # noqa: S701
    template = env.from_string(raw)
    return template.render(**template_vars)
