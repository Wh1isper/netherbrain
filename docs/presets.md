# Presets and Workspaces

Presets define how an agent behaves: which model it uses, what tools it has, and what projects it operates on. Workspaces are named collections of project directories that can be reused across conversations.

______________________________________________________________________

## Concepts

**Preset**: A saved agent configuration stored in PostgreSQL. It specifies the model, system prompt, enabled toolsets, environment, and optional subagents. Referenced by `preset_id` when starting a conversation.

**Workspace**: A named, ordered list of `project_id` slugs, stored in PostgreSQL. Workspaces are optional shortcuts -- you can always pass `project_ids` directly in an API request for ad-hoc use.

**Project**: A directory on the host filesystem, identified by a slug. Projects are not registered entities -- any slug used as a `project_id` maps to `{NETHER_DATA_ROOT}/projects/{project_id}/`, auto-created on first access.

______________________________________________________________________

## Managing Presets

### Create a preset

```bash
curl -X POST http://localhost:8000/api/presets/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "preset_id": "coding-agent",
    "name": "Coding Agent",
    "description": "General-purpose coding assistant.",
    "model": {"name": "anthropic:claude-sonnet-4-20250514"},
    "system_prompt": "You are a skilled software engineer.",
    "toolsets": [
      {"toolset_name": "core", "enabled": true}
    ],
    "is_default": true
  }'
```

### List presets

```bash
curl http://localhost:8000/api/presets/list \
  -H "Authorization: Bearer $TOKEN"
```

### Update a preset

Only the fields you provide are updated (partial update).

```bash
curl -X POST http://localhost:8000/api/presets/coding-agent/update \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"system_prompt": "You are an expert Python engineer."}'
```

### Delete a preset

```bash
curl -X POST http://localhost:8000/api/presets/coding-agent/delete \
  -H "Authorization: Bearer $TOKEN"
```

______________________________________________________________________

## Preset Fields

### Model

Controls which LLM is used and its inference parameters.

| Field          | Type   | Required | Description                                                                |
| -------------- | ------ | -------- | -------------------------------------------------------------------------- |
| name           | string | Yes      | Provider-qualified model name (e.g., `anthropic:claude-sonnet-4-20250514`) |
| context_window | int    | No       | Override context window size                                               |
| temperature    | float  | No       | Sampling temperature                                                       |
| max_tokens     | int    | No       | Max output tokens                                                          |

**Provider prefix examples:**

| Prefix        | Provider               |
| ------------- | ---------------------- |
| `anthropic:`  | Anthropic (Claude)     |
| `openai:`     | OpenAI (GPT-4o, etc.)  |
| `google-gla:` | Google (Gemini)        |
| `openrouter:` | OpenRouter (any model) |
| `ollama:`     | Local Ollama instance  |

For OpenAI-compatible providers, set `{GATEWAY}_API_KEY` and `{GATEWAY}_BASE_URL` environment variables. See [configuration](./configuration.md#llm-providers).

### System Prompt

The system prompt is a [Jinja2](https://jinja.palletsprojects.com/) template. The following variables are available at render time:

| Variable           | Type        | Description                                     |
| ------------------ | ----------- | ----------------------------------------------- |
| `project_ids`      | list[str]   | Active project IDs for this run                 |
| `default_project`  | str or None | First project ID (agent's working directory)    |
| `environment_mode` | str         | `"local"` or `"sandbox"`                        |
| `model_name`       | str         | Model identifier (e.g., `anthropic:claude-...`) |
| `preset_id`        | str         | Active preset ID                                |
| `date`             | str         | Current date in `YYYY-MM-DD` format             |

Example template:

```
You are a software engineer working on {{ default_project }}.
Current date: {{ date }}.
{% if project_ids | length > 1 %}
You also have access to: {{ project_ids[1:] | join(', ') }}
{% endif %}
Be concise and direct.
```

### Toolsets

Toolsets group related tools. Only enabled toolsets are available to the agent.

`core` is a convenience alias that enables all standard toolsets at once.

| Toolset      | Tools                                                             |
| ------------ | ----------------------------------------------------------------- |
| `core`       | Alias for all standard toolsets listed below                      |
| `filesystem` | view, edit, multi_edit, write, ls, glob, grep, mkdir, move, copy  |
| `shell`      | shell                                                             |
| `web`        | search, search_stock_image, search_image, scrape, fetch, download |
| `content`    | load_media_url                                                    |
| `multimodal` | read_image, read_video                                            |
| `document`   | pdf_convert, office_to_markdown                                   |
| `enhance`    | task_create, task_get, task_update, task_list                     |
| `context`    | handoff                                                           |

Note: `document` requires optional Python dependencies (`pymupdf` for PDF, `markitdown` for Office). Tools are silently omitted if dependencies are not installed.

To use all standard tools, a single `core` spec is sufficient:

```json
[{"toolset_name": "core", "enabled": true}]
```

To disable specific tools within an enabled toolset, use `exclude_tools`:

```json
{"toolset_name": "web", "enabled": true, "exclude_tools": ["SearchStockImageTool", "SearchImageTool"]}
```

### Environment

Controls where the agent operates.

| Field             | Type         | Default      | Description                                                |
| ----------------- | ------------ | ------------ | ---------------------------------------------------------- |
| mode              | enum         | `local`      | `local` (host) or `sandbox` (Docker container)             |
| workspace_id      | string       | null         | Reference a saved workspace                                |
| project_ids       | list[string] | null         | Inline project list (mutually exclusive with workspace_id) |
| container_id      | string       | null         | Docker container ID (required for sandbox mode)            |
| container_workdir | string       | `/workspace` | Working directory inside container (sandbox mode only)     |

**local mode**: Agent uses the host filesystem and runs shell commands on the host directly.

**sandbox mode**: Agent executes shell commands via `docker exec` inside the specified container. File I/O happens on the host but is mapped to virtual paths inside the container. You are responsible for starting the container and mounting the projects root directory.

Example sandbox environment:

```json
{
  "mode": "sandbox",
  "project_ids": ["my-project"],
  "container_id": "my-dev-container",
  "container_workdir": "/workspace"
}
```

### Tool Config

Non-secret per-preset tool settings. API keys are always read from environment variables.

| Field                              | Type   | Default | Description                            |
| ---------------------------------- | ------ | ------- | -------------------------------------- |
| skip_url_verification              | bool   | true    | Skip SSRF URL verification             |
| enable_load_document               | bool   | false   | Enable document URL parsing            |
| image_understanding_model          | string | null    | Model for image understanding          |
| image_understanding_model_settings | dict   | null    | Settings for image understanding model |
| video_understanding_model          | string | null    | Model for video understanding          |
| video_understanding_model_settings | dict   | null    | Settings for video understanding model |

### MCP Servers

Connect external [Model Context Protocol](https://modelcontextprotocol.io/) servers. Only network-based transports are supported (no stdio).

| Field       | Type   | Default           | Description                                |
| ----------- | ------ | ----------------- | ------------------------------------------ |
| url         | string | (required)        | MCP server HTTP endpoint                   |
| transport   | enum   | `streamable_http` | `streamable_http` or `sse`                 |
| headers     | dict   | null              | Custom HTTP headers (e.g., auth tokens)    |
| tool_prefix | string | null              | Prefix to namespace tools from this server |
| timeout     | float  | null              | Connection timeout in seconds              |

Example:

```json
{
  "mcp_servers": [
    {
      "url": "http://localhost:3000/mcp",
      "transport": "streamable_http",
      "tool_prefix": "github",
      "headers": {"Authorization": "Bearer ghp_..."}
    }
  ]
}
```

MCP server tools appear alongside built-in toolset tools during execution.

### Subagents

Configure subagent delegation for this preset.

| Field           | Type | Description                                    |
| --------------- | ---- | ---------------------------------------------- |
| include_builtin | bool | Include SDK built-in subagents (default: true) |
| async_enabled   | bool | Enable `async_delegate` tool (default: false)  |
| refs            | list | References to other presets as named subagents |

Each subagent reference (`refs` entry):

| Field       | Type   | Description                                     |
| ----------- | ------ | ----------------------------------------------- |
| preset_id   | string | Referenced preset's ID                          |
| name        | string | Name shown to the agent when delegating         |
| description | string | When to use this subagent (shown to LLM)        |
| instruction | string | Optional text injected into the parent's prompt |

Example -- a main agent that can delegate to a specialist:

```json
{
  "subagents": {
    "include_builtin": false,
    "async_enabled": false,
    "refs": [
      {
        "preset_id": "code-reviewer",
        "name": "code-reviewer",
        "description": "Review code for correctness, security, and style."
      }
    ]
  }
}
```

______________________________________________________________________

## Managing Workspaces

A workspace saves a list of project directories under a reusable name.

### Create a workspace

```bash
curl -X POST http://localhost:8000/api/workspaces/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "my-project",
    "name": "My Project",
    "projects": ["my-project", "shared-lib"]
  }'
```

### Use a workspace in a conversation

```bash
curl -X POST http://localhost:8000/api/conversations/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "preset_id": "coding-agent",
    "workspace_id": "my-project",
    "input": [{"type": "text", "text": "Review the codebase."}]
  }'
```

The first project in the list becomes the agent's default working directory. Additional projects are available as allowed paths.

______________________________________________________________________

## Seed File

Pre-configure presets and workspaces declaratively from a TOML file.

**On startup**: Set `NETHER_SEED_FILE=/path/to/seed.toml` to apply on every boot.

**Manual**: Run `netherbrain db seed [file]` (default: `seed.toml`).

**Semantics**: Creates entries if missing, updates if existing. Removing an entry from the file does **not** delete it from the database.

**Required fields**: `preset_id` and `workspace_id` must be set explicitly (no auto-generation).

### Format

```toml
# Presets
[[presets]]
preset_id = "coding-agent"
name = "Coding Agent"
description = "General-purpose coding assistant with full tool access."
is_default = true
system_prompt = """
You are a skilled software engineer working in a shared project directory.
You can read, edit, and create files, run shell commands, and search the web.
"""

[presets.model]
name = "anthropic:claude-sonnet-4-20250514"

[[presets.toolsets]]
toolset_name = "core"
enabled = true

[[presets]]
preset_id = "chat-only"
name = "Chat Only"
description = "Pure conversation mode without tools or file access."
system_prompt = "You are a helpful assistant."

[presets.model]
name = "anthropic:claude-sonnet-4-20250514"

# Workspaces
[[workspaces]]
workspace_id = "my-project"
name = "My Project"
projects = ["my-project"]

[workspaces.metadata]
source = "seed"
```

The seed file format mirrors the `PresetCreate` and `WorkspaceCreate` API schemas. All preset and workspace fields are supported.
