# TODO

Implementation roadmap derived from spec/ documents. Organized by priority and dependency.

## Status Legend

- `[x]` Done
- `[ ]` Not started
- `[-]` Partially done

## Phase 1: Foundation (DB, CRUD, Lifecycle)

- [x] DB tables (ORM) for all entities (presets, workspaces, conversations, sessions, mailbox)
- [x] Alembic migrations and CLI (`netherbrain db`)
- [x] Settings (`pydantic-settings`, `get_settings()` with `lru_cache`)
- [x] DB engine factory with production pool settings
- [x] Redis client initialization in lifespan
- [x] FastAPI dependencies (`DbSession`, `RedisClient` with 503 fallback)
- [x] Pydantic API models (Create/Update/Response for presets, workspaces, conversations)
- [x] CRUD routers: presets (with `is_default` mutual exclusion), workspaces, conversations (read-only)
- [x] App lifespan (DB/Redis init + graceful shutdown with session drain)
- [x] SSE graceful drain (`sse-starlette` AppStatus)
- [x] Session registry (drain, interrupt_all, transport-aware queries, shutdown lifecycle)
- [x] Domain models (preset, session, workspace, enums, events)
- [x] Integration tests (23 tests: CRUD, DB, Redis)

## Phase 2: State Store and Session Manager

Persistence layer for session state (context, history, display messages).

- [x] State store interface (read/write state.json)
- [x] State store: display_messages.json read/write (separate optional file alongside state.json)
- [x] Local filesystem implementation (`{data_dir}/sessions/{session_id}/`, atomic writes)
- [x] S3 implementation (optional)
- [x] Session manager: create session (PG index + conversation + registry)
- [x] Session manager: commit session (write store + update PG status + unregister)
- [x] Session manager: get session (PG index + state store read)
- [x] Session manager: get session loads display_messages by default
- [x] Session manager: list sessions by conversation
- [x] Startup recovery: mark orphaned `status=created` sessions as `failed`
- [x] Conversation update API (title, metadata, status, default_preset_id)
- [x] Conversation turns endpoint (input + final_message from PG)
- [x] Conversation turns: `include_display` param to load display_messages from State Store
- [x] Conversation sessions list endpoint
- [x] Session get endpoint (with optional state hydration)

## Phase 3: Execution Coordinator and SDK Integration

Core agent execution pipeline.

- [x] Config resolver (load preset + merge override + resolve workspace + inject env vars)
- [x] Environment setup: local mode (project path resolution under DATA_ROOT)
- [x] Environment setup: sandbox mode (SandboxEnvironment with DockerShell + VirtualLocalFileOperator)
- [x] SDK adapter: map resolved config to `create_agent` + `stream_agent`
- [x] Input mapping (text/url/file/binary parts, content_mode file/inline)
- [x] System prompt rendering (Jinja2 template)
- [x] Execution coordinator: setup -> run -> finalize pipeline
- [x] Session commit flow: export state, write store, update PG
- [x] Display messages compression: compress AGUIProtocol buffer into AG-UI chunk events at commit time
- [x] Write display_messages.json to State Store during session commit
- [x] Deferred tool handling (awaiting_tool_results status, user_interactions, tool_results)
- [x] External MCP server support (McpServerSpec in preset, SSE/Streamable HTTP transports)

## Phase 4: Event Protocol and Transport

Event processing and delivery.

- [x] Protocol event types (AG-UI re-exports, extension event names, SSE encoding helpers)
- [x] Protocol adapter interface (`ProtocolAdapter` with `on_event` / `on_error`)
- [x] AG-UI protocol adapter (`AGUIProtocol`: SDK StreamEvent -> AG-UI BaseEvent)
- [x] Pipeline lifecycle events (`PipelineStarted`, `PipelineCompleted`, `PipelineFailed`, `UsageSnapshot`)
- [x] Per-model usage tracking (`ModelUsage` / `PipelineUsage` dataclasses, aggregation by model_id)
- [x] Usage snapshot hook (`UsageSnapshotEmitter` post-node hook for real-time usage)
- [x] Event transport protocol (`EventTransport`: `send` / `close` interface)
- [x] SSE transport (queue-backed, non-blocking `close` to avoid teardown stall)
- [x] Redis stream transport (XADD to `nether:stream:{session_id}`, configurable TTL)
- [x] Stream-to-SSE bridge (`bridge_stream_to_sse`: XREAD + `Last-Event-ID` resume + idle timeout)

## Phase 5: Chat API (Conversation-Level Endpoints)

High-level conversation operations.

- [x] `POST /api/conversations/run` (new conversation or continue)
- [x] `POST /api/conversations/{id}/fork` (fork new conversation from session)
- [x] `POST /api/conversations/{id}/interrupt` (interrupt all active sessions)
- [x] `POST /api/conversations/{id}/steer` (steer active agent session)
- [x] `GET /api/conversations/{id}/events` (stream-to-SSE bridge for active session)
- [x] `POST /api/conversations/{id}/update` (title, metadata, status, default_preset_id)
- [x] `GET /api/conversations/{id}/turns` (display messages across sessions)
- [x] `GET /api/conversations/{id}/sessions` (list sessions with status)
- [x] Concurrency guard: at most one running agent session per conversation (409)

## Phase 6: Session API (Lower-Level)

Direct session control.

- [x] `POST /api/sessions/execute` (explicit session creation and execution)
- [x] `GET /api/sessions/{id}/get` (PG index + display_messages by default, optional SDK state)
- [x] `GET /api/sessions/{id}/status` (check registry then PG)
- [x] `GET /api/sessions/{id}/events` (stream-to-SSE bridge with resume)
- [x] `POST /api/sessions/{id}/interrupt`
- [x] `POST /api/sessions/{id}/steer`

## Phase 7: Control (Interrupt and Steering)

In-process control via session registry.

- [x] Interrupt handler: `registry.get()` -> `streamer.interrupt()` -> partial commit
- [x] Steering handler: `registry.get()` -> `context.send_message()` -> consumed at next turn
- [x] Input mapping for steering (same format as run)

## Phase 8: Async Agents and Mailbox

Async subagent orchestration.

- [x] `async_delegate` tool (check registry, self-call execute, update registry)
- [x] Mailbox: post `subagent_result` / `subagent_failed` on subagent terminal state
- [x] `POST /api/conversations/{id}/fire` (drain mailbox, render prompt, execute continuation)
- [x] `GET /api/conversations/{id}/mailbox` (query messages with delivery status)
- [x] Mailbox message rendering (single and multi-result templates)
- [x] Delivery tracking (`delivered_to` prevents duplicate delivery)

## Phase 9: Authentication

- [x] Auth middleware: validate `Authorization: Bearer {token}` on all endpoints except health
- [x] Skip auth for `GET /api/health`
- [x] Auth middleware: fail-closed when app state unavailable (503)
- [x] Auth middleware: constant-time token comparison (hmac.compare_digest)

## Phase 10: Health Endpoint Enhancement

- [x] Enrich health response with PG and Redis connectivity status

## Phase 10.5: Hardening and Seed Data

- [x] Path traversal protection in file input handling (containment check)
- [x] Path traversal protection in SPA fallback file serving
- [x] Mailbox claim rollback on launch failure (fire_conversation)
- [x] Router layering fix: move DB query from sessions router to manager
- [x] Partial unique index on presets.is_default (DB migration)
- [x] Race-safe preset/workspace creation (catch IntegrityError)
- [x] Fix get_session_status return type annotation
- [x] Harden base64 input decoding (validate=True)
- [x] Seed data: TOML-based preseed for presets and workspaces
- [x] Seed data: `netherbrain db seed <file>` CLI command
- [x] Seed data: auto-apply on startup via NETHER_SEED_FILE setting
- [x] settings.py: add `extra="ignore"` so non-`NETHER_*` env vars in `.env` are silently ignored
- [x] Toolset capability discovery: `GET /api/toolsets` endpoint (returns available toolsets + tools, no DB)
- [x] Toolset tests: 6 integration tests covering schema, registry completeness, core alias, auth

## Phase 11: Web UI

### Foundation (done)

- [x] Tech stack: Tailwind CSS v4 + shadcn/ui + Zustand + react-markdown + Shiki + lucide-react
- [x] shadcn/ui components: button, input, textarea, dropdown-menu, scroll-area, separator, tabs, badge, dialog, tooltip, sheet, skeleton, select, label
- [x] API client: `client.ts` (auth token, error handling), `types.ts` (TypeScript interfaces matching backend)
- [x] API modules: `workspaces.ts`, `conversations.ts`, `presets.ts` (includes `listToolsets`)
- [x] Zustand store: auth token, theme (dark/light), current workspace, conversation list, sidebar state
- [x] App shell: auth gate (token input) + sidebar + main content + routing
- [x] Routing: `/` `/c/:id` → Chat, `/settings` → Settings
- [x] Sidebar: workspace selector dropdown, conversation list, theme toggle, settings nav, collapse/expand
- [x] Default workspace: auto-create `webui-default` on first launch

### Settings page

- [x] Settings: preset list (name, model badge, default indicator)
- [x] Settings: preset create/edit form (model, system prompt, toolset checklist from `/api/toolsets`, subagents)
- [x] Settings: preset delete with confirmation dialog
- [x] Settings: preset clone action
- [x] Settings: workspace list (name, folders, default badge, filtered to `source: "webui"`)
- [x] Settings: workspace create/edit form (name, folder list add/remove)
- [x] Settings: workspace delete with confirmation (block default workspace delete)

### Chat page

- [x] Chat: load and display conversation history (`GET /conversations/{id}/turns`)
- [x] Chat: message input (auto-resize textarea, Enter to send, Shift+Enter newline)
- [x] Chat: send message (`POST /conversations/run`) with SSE stream consumption
- [x] Chat: streaming text rendering (incremental, auto-scroll)
- [x] Chat: Markdown rendering with Shiki code highlight and copy button
- [x] Chat: tool call collapsible cards (collapsed: name + summary; expanded: args + output)
- [x] Chat: thinking/reasoning section (collapsed by default)
- [x] Chat: streaming state controls (Stop button -> interrupt, Send while streaming -> steer)
- [x] Chat: conversation header (editable title, preset badge)
- [ ] Chat: SSE reconnect on drop (check status, reattach or reload turns)
- [ ] Chat: mobile responsive (full-screen chat view, back button)
- [ ] Chat: Shiki bundle optimization (dynamic import for languages)

## Phase 12: IM Gateway

- [ ] Runtime client: HTTP wrapper for agent-runtime API
- [ ] Runtime client: SSE event consumption via bridge endpoint
- [ ] Conversation mapper: in-memory channel \<-> conversation_id cache
- [ ] Conversation mapper: recovery via metadata query on restart
- [ ] Bridge core: message flow orchestration (receive -> run -> stream -> render)
- [ ] Discord adapter: bot lifecycle, message handling, thread management
- [ ] Message rendering: protocol events -> Discord messages (chunking, formatting)

## Completed Fixes (from code review)

- Auth middleware fail-closed, constant-time compare
- Path traversal in input.py and SPA fallback
- Mailbox claim rollback on launch failure
- Router DB query moved to manager (sessions status)
- Partial unique index on presets.is_default
- Race-safe create for presets and workspaces
- get_session_status return type fixed
- base64 decode validation
