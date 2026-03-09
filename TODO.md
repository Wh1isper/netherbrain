# TODO

## Completed

The agent-runtime (backend) and web UI (frontend) are feature-complete:

- Foundation: DB, CRUD, settings, migrations, CLI
- State store (local + S3), session manager, startup recovery
- Execution pipeline: resolver, environment, SDK adapter, coordinator
- Event protocol (AG-UI), SSE + Redis stream transport, bridge
- Full conversation and session API (run, fork, steer, interrupt, fire, mailbox)
- Async delegate tool, mailbox orchestration
- Authentication (root token, JWT, API keys, bootstrap admin)
- File serving, interactive shell (WebSocket PTY, Docker exec)
- Observability (Langfuse integration)
- CI/CD (quality checks, tests, Docker image, PyPI release)
- Web UI: Chat, Settings, Files pages with all features and optimizations

## In Progress

Nothing currently in progress.

## Remaining: IM Gateway

The im-gateway is the only unimplemented component. Spec is ready (`spec/im_gateway/`), code is a stub.

### Runtime Client

- [ ] HTTP wrapper for agent-runtime API (run, steer, interrupt, fire, get, lookup)
- [ ] SSE event consumption via bridge endpoint (`GET /sessions/{id}/events`)
- [ ] Busy handling: 409 conflict -> fallback to steer -> retry as new run

### Conversation Mapper

- [ ] In-memory `(platform, channel_id) -> conversation_id` cache
- [ ] Lazy recovery on cache miss: query runtime by `metadata` containment
- [ ] Populate cache on new conversation creation

### Bridge Core

- [ ] Message flow orchestration: `on_message` -> resolve -> run/steer -> stream -> render
- [ ] Content accumulator (buffer deltas, rate-limited flush)
- [ ] Message splitter (respect platform char limits, preserve code blocks)
- [ ] Platform formatter (Markdown -> platform-native)

### Discord Adapter

- [ ] Add `discord.py` dependency to `pyproject.toml`
- [ ] Bot lifecycle (connect, intents, presence status reflecting runtime connectivity)
- [ ] Message handling: filter (bot, mention, thread, DM), parse content, map attachments
- [ ] Thread management: auto-create threads from channel mentions, thread naming
- [ ] DM mode: single conversation per user
- [ ] Slash commands: `/ask`, `/preset`, `/reset`, `/interrupt`
- [ ] Context menu: "Ask Agent" message command
- [ ] Streaming updates: typing indicator, edit-in-place with rate limiting (~1s), overflow to new message
- [ ] Tool call display: inline status during streaming, collapsed embed on completion
- [ ] Thinking content: hidden or spoiler-tagged
- [ ] Error handling: runtime unreachable, agent failure, rate limits, invalid preset

### Gateway CLI and Config

- [ ] `netherbrain gateway` command: wire up Discord bot with bridge core
- [ ] Environment config: `RUNTIME_URL`, `RUNTIME_AUTH_TOKEN`, `DISCORD_BOT_TOKEN`, `DEFAULT_PRESET_ID`
- [ ] Gateway settings class (pydantic-settings, separate from agent-runtime settings)

### Testing

- [ ] Runtime client unit tests (httpx mock)
- [ ] Conversation mapper tests (cache hit/miss/recovery)
- [ ] Bridge core tests (message flow, busy handling)
- [ ] Message splitter tests (char limits, code block preservation)
- [ ] Discord adapter integration tests (discord.py bot mock)
