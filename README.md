# netherbrain

[![Release](https://img.shields.io/github/v/release/wh1isper/netherbrain)](https://img.shields.io/github/v/release/wh1isper/netherbrain)
[![Build status](https://img.shields.io/github/actions/workflow/status/wh1isper/netherbrain/main.yml?branch=main)](https://github.com/wh1isper/netherbrain/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/wh1isper/netherbrain)](https://img.shields.io/github/commit-activity/m/wh1isper/netherbrain)
[![License](https://img.shields.io/github/license/wh1isper/netherbrain)](https://img.shields.io/github/license/wh1isper/netherbrain)

Netherbrain is a self-hosted agent service for homelab use. It exposes a persistent agent runtime with a REST API, and will connect to IM platforms (Discord, Telegram) via the IM Gateway.

The web UI and IM Gateway are currently under development.

______________________________________________________________________

## Features

- **Persistent conversations** -- Sessions form a git-like DAG; continue, fork, or resume any point in history.
- **Flexible agent configuration** -- Define agent presets with model selection, system prompts, toolsets, and project environments. Manage via API.
- **Built-in toolsets** -- File operations, shell, web search, document processing, and more.
- **MCP server support** -- Connect any external Model Context Protocol server to extend agent capabilities.
- **Async subagents** -- Spawn parallel subagent sessions within a conversation; collect results via mailbox.
- **IM integration** -- IM Gateway for Discord and Telegram (work in progress).
- **Web UI** -- Chat interface and settings (work in progress).
- **Sandbox mode** -- Run agent shell commands inside a Docker container while keeping file I/O on the host.
- **Observability** -- Optional Langfuse integration for LLM tracing and cost tracking.
- **S3-compatible state storage** -- Swap local filesystem for any S3-compatible backend.

______________________________________________________________________

## Architecture

```mermaid
flowchart LR
    WUI[Web UI] --> RT[agent-runtime]
    API_CLIENT[API Client] --> RT
    GW[im-gateway] -->|HTTP + SSE| RT
    RT --> LLM[LLM Provider]
    RT <--> PG[(PostgreSQL)]
    RT <--> RD[(Redis)]
    RT <--> FS[(Local FS / S3)]
```

The **agent-runtime** is a FastAPI service that manages agent execution, session persistence, and event streaming. It serves the built-in web UI at `/`.

The **im-gateway** is a stateless HTTP client that translates IM platform events (Discord messages, etc.) into runtime API calls. It stores no state of its own.

______________________________________________________________________

## Quick Start

### With Docker

```bash
# Start PostgreSQL and Redis (example docker-compose.yml in docs)
docker compose up -d postgres redis

# Run database migrations
docker run --rm \
  --network host \
  -e NETHER_DATABASE_URL="postgresql+psycopg://netherbrain:netherbrain@localhost:5432/netherbrain" \
  ghcr.io/wh1isper/netherbrain db upgrade

# Run the agent runtime
docker run -d \
  --name netherbrain \
  --network host \
  -e NETHER_DATABASE_URL="postgresql+psycopg://netherbrain:netherbrain@localhost:5432/netherbrain" \
  -e NETHER_REDIS_URL="redis://localhost:6379/0" \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v /path/to/data:/app/data \
  ghcr.io/wh1isper/netherbrain

# Get the auth token (if NETHER_AUTH_TOKEN was not set)
docker logs netherbrain | grep "generated token"
```

Open `http://localhost:9001` for the web UI.

### From Source

Requires Python 3.13+ and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/wh1isper/netherbrain.git
cd netherbrain
make install
make infra-up          # starts PostgreSQL on :15432, Redis on :16379
cp dev/dev.env .env    # edit .env to add your LLM API key
make db-upgrade
make run-agent
```

______________________________________________________________________

## Documentation

| Document                                   | Description                                       |
| ------------------------------------------ | ------------------------------------------------- |
| [Getting Started](docs/getting-started.md) | Full setup guide (Docker and from source)         |
| [Configuration](docs/configuration.md)     | All environment variables                         |
| [Presets and Workspaces](docs/presets.md)  | Configure agents, tools, and project environments |
| [Architecture](docs/architecture.md)       | System design and key concepts                    |

______________________________________________________________________

## License

[BSD 3-Clause](LICENSE)
