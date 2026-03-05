# netherbrain

[![Release](https://img.shields.io/github/v/release/wh1isper/netherbrain)](https://img.shields.io/github/v/release/wh1isper/netherbrain)
[![Build status](https://img.shields.io/github/actions/workflow/status/wh1isper/netherbrain/main.yml?branch=main)](https://github.com/wh1isper/netherbrain/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/wh1isper/netherbrain)](https://img.shields.io/github/commit-activity/m/wh1isper/netherbrain)
[![License](https://img.shields.io/github/license/wh1isper/netherbrain)](https://img.shields.io/github/license/wh1isper/netherbrain)

Netherbrain is a self-hosted agent service for homelab use. It exposes a persistent agent runtime with a REST API, a built-in web UI, and connects to IM platforms (Discord, Telegram) via the IM Gateway.

______________________________________________________________________

## Features

- **Persistent conversations** -- Sessions form a git-like DAG; continue, fork, or resume any point in history.
- **Resilient streaming** -- Web UI uses Redis-backed stream transport with automatic reconnection on connection drop. Falls back to direct SSE when Redis is unavailable.
- **Flexible agent configuration** -- Define agent presets with model selection, system prompts, toolsets, and project environments. Manage via API or web UI.
- **Built-in toolsets** -- File operations, shell, web search, document processing, and more.
- **MCP server support** -- Connect any external Model Context Protocol server to extend agent capabilities.
- **Async subagents** -- Spawn parallel subagent sessions within a conversation; collect results via mailbox.
- **Web UI** -- Chat interface and settings management, served at `/`.
- **IM integration** -- IM Gateway for Discord and Telegram (work in progress).
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

The **im-gateway** is a stateless HTTP client that translates IM platform events (Discord messages, etc.) into runtime API calls.

______________________________________________________________________

## Quick Start

Netherbrain requires **PostgreSQL** and **Redis**. Make sure they are running before proceeding.

### With pip

```bash
pip install netherbrain
```

### With uv

```bash
uv pip install netherbrain

# Or run directly without installing:
uvx netherbrain --help
```

### Run the Agent Runtime

```bash
# Set required environment variables (or put them in a .env file)
export NETHER_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/netherbrain"
export NETHER_REDIS_URL="redis://localhost:6379/0"
export NETHER_AUTH_TOKEN="your-secret-token"
export ANTHROPIC_API_KEY="sk-ant-..."   # or any LLM provider key

# Run database migrations
netherbrain db upgrade

# Start the agent runtime (default: http://0.0.0.0:9001)
netherbrain agent
```

Open `http://localhost:9001` for the web UI. On first launch, an `admin` user is created with password equal to `NETHER_AUTH_TOKEN`.

### With Docker

```bash
# Run database migrations
docker run --rm --network host \
  -e NETHER_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/netherbrain" \
  ghcr.io/wh1isper/netherbrain db upgrade

# Run the agent runtime
docker run -d --name netherbrain --network host \
  -e NETHER_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/netherbrain" \
  -e NETHER_REDIS_URL="redis://localhost:6379/0" \
  -e NETHER_AUTH_TOKEN="your-secret-token" \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v /path/to/data:/app/data \
  ghcr.io/wh1isper/netherbrain
```

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

## CLI Reference

```
netherbrain agent          Start the agent runtime server
netherbrain gateway        Start the IM gateway
netherbrain db upgrade     Run database migrations to latest
netherbrain db downgrade   Roll back database by one migration
netherbrain db import      Import presets/workspaces from a TOML file
netherbrain db create-admin Create an admin user manually
```

Run `netherbrain --help` for full details.

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
