# Getting Started

Netherbrain is a self-hosted agent service for homelab use. It exposes a chat API and web UI, and can connect to IM platforms (Discord, Telegram) via the IM Gateway.

## Prerequisites

- PostgreSQL 14+
- Redis 6+
- Docker (optional, for containerized deployment or sandbox mode)
- An LLM API key (OpenAI, Anthropic, or any OpenAI-compatible provider)

______________________________________________________________________

## Option 1: Docker (Recommended)

The easiest way to run Netherbrain is with Docker. The image packages both the agent-runtime server and the built web UI.

### 1. Start infrastructure

You need PostgreSQL and Redis. A minimal `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: netherbrain
      POSTGRES_PASSWORD: netherbrain
      POSTGRES_DB: netherbrain
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"

volumes:
  pg_data:
```

### 2. Run the agent

The service does **not** run database migrations automatically. You must run them once before starting:

```bash
docker run --rm \
  -e NETHER_DATABASE_URL="postgresql+psycopg://netherbrain:netherbrain@localhost:5432/netherbrain" \
  ghcr.io/wh1isper/netherbrain db upgrade
```

Then start the agent:

```bash
docker run -d \
  --name netherbrain \
  --network host \
  -e NETHER_DATABASE_URL="postgresql+psycopg://netherbrain:netherbrain@localhost:5432/netherbrain" \
  -e NETHER_REDIS_URL="redis://localhost:6379/0" \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v /path/to/data:/app/data \
  ghcr.io/wh1isper/netherbrain
```

If `NETHER_AUTH_TOKEN` is not set, a token is generated and logged at startup.

```bash
# Retrieve the generated auth token
docker logs netherbrain | grep "generated token"
```

The web UI is available at `http://localhost:8000`.

### 3. Run the gateway (optional)

To connect a Discord bot:

```bash
docker run -d \
  --name netherbrain-gateway \
  -e RUNTIME_URL="http://localhost:8000" \
  -e RUNTIME_AUTH_TOKEN="<token-from-above>" \
  -e DISCORD_BOT_TOKEN="<your-discord-bot-token>" \
  --network host \
  ghcr.io/wh1isper/netherbrain gateway
```

______________________________________________________________________

## Option 2: From Source

### 1. Install dependencies

Requires Python 3.13+ and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/wh1isper/netherbrain.git
cd netherbrain
make install
```

### 2. Start infrastructure

```bash
make infra-up      # starts PostgreSQL on :15432, Redis on :16379
```

### 3. Configure environment

```bash
cp dev/dev.env .env
# Edit .env and add your LLM API keys
```

A minimal `.env`:

```env
NETHER_DATABASE_URL=postgresql+psycopg://netherbrain:netherbrain@localhost:15432/netherbrain
NETHER_REDIS_URL=redis://localhost:16379/0
ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Run migrations

```bash
make db-upgrade
```

### 5. Start the service

```bash
make run-agent
# or for development with hot reload:
make dev
```

The service starts on `http://localhost:8000`. The auth token is logged at startup if not configured.

______________________________________________________________________

## First Steps

### Access the web UI

Open `http://localhost:8000` in your browser. The web UI is currently a placeholder; full chat and configuration interfaces are under development. Use the API directly in the meantime.

### Make your first API call

```bash
TOKEN="<your-auth-token>"

# Start a new conversation
curl -X POST http://localhost:8000/api/conversations/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "preset_id": "coding-agent",
    "input": [{"type": "text", "text": "Hello, what can you do?"}]
  }'
```

If no presets exist yet, create one first:

```bash
curl -X POST http://localhost:8000/api/presets/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "preset_id": "my-agent",
    "name": "My Agent",
    "model": {"name": "anthropic:claude-sonnet-4-20250514"},
    "system_prompt": "You are a helpful assistant.",
    "toolsets": [],
    "is_default": true
  }'
```

Or use a [seed file](./presets.md#seed-file) to pre-configure presets on startup.

### Check service health

```bash
curl http://localhost:8000/api/health
```

______________________________________________________________________

## Data Storage

By default, Netherbrain stores all data under `./data` relative to the working directory:

```
data/
  projects/     # agent working directories (one per project_id)
  sessions/     # session state blobs (state.json, display_messages.json)
```

Set `NETHER_DATA_ROOT` to an absolute path for production use. See [configuration](./configuration.md) for S3 state storage.

______________________________________________________________________

## Next Steps

- [Configuration reference](./configuration.md) - all environment variables
- [Presets and workspaces](./presets.md) - configure agents, tools, and project contexts
- [Architecture overview](./architecture.md) - understand the system design
