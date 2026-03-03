# Configuration Reference

All agent-runtime settings are read from environment variables prefixed with `NETHER_`. A `.env` file in the working directory is loaded automatically.

LLM API keys and tool API keys are **not** `NETHER_`-prefixed -- they follow the conventions of the underlying SDK and are read directly by the agent.

______________________________________________________________________

## Infrastructure

| Variable              | Required | Default | Description                                               |
| --------------------- | -------- | ------- | --------------------------------------------------------- |
| `NETHER_DATABASE_URL` | Yes      | -       | PostgreSQL connection string (`postgresql+psycopg://...`) |
| `NETHER_REDIS_URL`    | Yes      | -       | Redis connection string (`redis://...`)                   |
| `NETHER_LOG_LEVEL`    | No       | `INFO`  | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`        |

### Example

```env
NETHER_DATABASE_URL=postgresql+psycopg://netherbrain:netherbrain@localhost:5432/netherbrain
NETHER_REDIS_URL=redis://localhost:6379/0
```

______________________________________________________________________

## Data Storage

| Variable             | Required | Default  | Description                                                      |
| -------------------- | -------- | -------- | ---------------------------------------------------------------- |
| `NETHER_DATA_ROOT`   | No       | `./data` | Root directory for all managed data (projects and session state) |
| `NETHER_DATA_PREFIX` | No       | -        | Optional namespace prefix inserted into all data paths           |
| `NETHER_STATE_STORE` | No       | `local`  | State storage backend: `local` or `s3`                           |

`DATA_ROOT` is the unified root for:

- `{DATA_ROOT}/projects/{project_id}/` - agent working directories
- `{DATA_ROOT}/sessions/{session_id}/` - session state blobs

When `DATA_PREFIX` is set, paths become `{DATA_ROOT}/{DATA_PREFIX}/projects/...` etc. Useful for multi-tenant or organizational separation on a shared volume.

### S3 State Storage

When `NETHER_STATE_STORE=s3`, session state blobs are stored in S3 instead of the local filesystem. Project directories remain on the local filesystem regardless.

| Variable               | Required | Default | Description                                                   |
| ---------------------- | -------- | ------- | ------------------------------------------------------------- |
| `NETHER_S3_ENDPOINT`   | Yes      | -       | S3 endpoint URL (e.g., `https://s3.amazonaws.com`)            |
| `NETHER_S3_BUCKET`     | Yes      | -       | S3 bucket name                                                |
| `NETHER_S3_REGION`     | No       | -       | AWS region (e.g., `us-east-1`)                                |
| `NETHER_S3_ACCESS_KEY` | No       | -       | Access key ID                                                 |
| `NETHER_S3_SECRET_KEY` | No       | -       | Secret access key                                             |
| `NETHER_S3_PATH_STYLE` | No       | `false` | Use path-style addressing (required for MinIO and compatible) |

______________________________________________________________________

## Authentication

| Variable            | Required | Default     | Description                 |
| ------------------- | -------- | ----------- | --------------------------- |
| `NETHER_AUTH_TOKEN` | No       | (generated) | Bearer token for API access |

All API endpoints require `Authorization: Bearer {token}`. If `NETHER_AUTH_TOKEN` is not set, a random token is generated at startup and logged at `WARNING` level:

```
WARNING  | netherbrain.agent_runtime.app:lifespan - No NETHER_AUTH_TOKEN set -- generated token: <token>
```

There is no user system. A single shared token protects the entire API.

______________________________________________________________________

## Server Options

| Variable                           | Required | Default   | Description                                         |
| ---------------------------------- | -------- | --------- | --------------------------------------------------- |
| `NETHER_HOST`                      | No       | `0.0.0.0` | Listen address                                      |
| `NETHER_PORT`                      | No       | `8000`    | Listen port                                         |
| `NETHER_GRACEFUL_SHUTDOWN_TIMEOUT` | No       | `7200`    | Seconds to wait for active sessions during shutdown |

The graceful shutdown timeout matches the maximum expected session duration (2 hours). During shutdown, the service drains active SSE connections and waits for running sessions to complete before exiting.

______________________________________________________________________

## Seed Data

| Variable           | Required | Default | Description                                       |
| ------------------ | -------- | ------- | ------------------------------------------------- |
| `NETHER_SEED_FILE` | No       | -       | Path to a TOML seed file applied on every startup |

When set, the seed file is applied on startup with upsert semantics. See [Presets and Workspaces](./presets.md#seed-file) for the file format.

______________________________________________________________________

## LLM Providers

LLM API keys are not `NETHER_`-prefixed. They are read directly by the agent via `ya-agent-sdk` / `pydantic-ai` conventions.

| Variable             | Description                                     |
| -------------------- | ----------------------------------------------- |
| `OPENAI_API_KEY`     | OpenAI API key                                  |
| `ANTHROPIC_API_KEY`  | Anthropic API key                               |
| `{GATEWAY}_API_KEY`  | Custom gateway API key (uppercase gateway name) |
| `{GATEWAY}_BASE_URL` | Custom gateway base URL                         |

To use an OpenAI-compatible provider (e.g., local Ollama, OpenRouter):

```env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

Then reference the model in your preset as `openrouter:mistral/mistral-7b`.

______________________________________________________________________

## Tool API Keys

Tool API keys are also not `NETHER_`-prefixed. They are loaded automatically from the environment by the SDK when the corresponding toolset is enabled in a preset.

| Variable                | Description                    |
| ----------------------- | ------------------------------ |
| `TAVILY_API_KEY`        | Web search (Tavily)            |
| `FIRECRAWL_API_KEY`     | Web scraping (Firecrawl)       |
| `GOOGLE_SEARCH_API_KEY` | Google Custom Search API key   |
| `GOOGLE_SEARCH_CX`      | Google Custom Search Engine ID |

______________________________________________________________________

## Observability (Langfuse)

Optional LLM tracing via [Langfuse](https://langfuse.com). Uses Langfuse's native env vars (not `NETHER_`-prefixed). Gracefully degrades to no-op when unconfigured.

| Variable                       | Required | Default       | Description                |
| ------------------------------ | -------- | ------------- | -------------------------- |
| `LANGFUSE_SECRET_KEY`          | Yes      | -             | Langfuse secret key        |
| `LANGFUSE_PUBLIC_KEY`          | Yes      | -             | Langfuse public key        |
| `LANGFUSE_HOST`                | Yes      | -             | Langfuse server URL        |
| `LANGFUSE_TRACING_ENVIRONMENT` | No       | `dev`         | Environment tag for traces |
| `OTEL_SERVICE_NAME`            | No       | `netherbrain` | Service name in traces     |

When Langfuse is configured, all LLM generations, tool calls, and token costs are traced.

______________________________________________________________________

## IM Gateway

The IM Gateway has its own configuration, separate from the agent-runtime.

| Variable             | Required | Description                                            |
| -------------------- | -------- | ------------------------------------------------------ |
| `RUNTIME_URL`        | Yes      | Agent runtime base URL (e.g., `http://localhost:8000`) |
| `RUNTIME_AUTH_TOKEN` | Yes      | Bearer token matching `NETHER_AUTH_TOKEN`              |
| `DISCORD_BOT_TOKEN`  | Yes\*    | Discord bot token (\* required for Discord)            |
| `DEFAULT_PRESET_ID`  | No       | Fallback agent preset when none is set                 |

The gateway has no database or Redis dependency. All state lives in the agent-runtime.

______________________________________________________________________

## Complete Example

A production `.env` for a typical homelab deployment:

```env
# Infrastructure
NETHER_DATABASE_URL=postgresql+psycopg://netherbrain:s3cr3t@postgres:5432/netherbrain
NETHER_REDIS_URL=redis://redis:6379/0

# Storage
NETHER_DATA_ROOT=/var/lib/netherbrain/data

# Auth
NETHER_AUTH_TOKEN=my-secret-token

# LLM
ANTHROPIC_API_KEY=sk-ant-...

# Tools
TAVILY_API_KEY=tvly-...

# Observability (optional)
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# Seed presets on startup
NETHER_SEED_FILE=/etc/netherbrain/seed.toml
```
