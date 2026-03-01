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

- [x] State store interface (read/write state.json and display_messages.json)
- [x] Local filesystem implementation (`{data_dir}/sessions/{session_id}/`, atomic writes)
- [x] S3 implementation (optional)
- [x] Session manager: create session (PG index + conversation + registry)
- [x] Session manager: commit session (write store + update PG status + unregister)
- [x] Session manager: get session (PG index + state store read)
- [x] Session manager: list sessions by conversation
- [x] Startup recovery: mark orphaned `status=created` sessions as `failed`
- [x] Conversation update API (title, metadata, status, default_preset_id)
- [x] Conversation turns endpoint (display_messages across sessions)
- [x] Conversation sessions list endpoint
- [x] Session get endpoint (with optional state hydration)

## Phase 3: Execution Coordinator and SDK Integration

Core agent execution pipeline.

- [x] Config resolver (load preset + merge override + resolve workspace + inject env vars)
- [x] Environment setup: local mode (project path resolution under DATA_ROOT)
- [-] Environment setup: docker mode (docker exec shell)
- [x] SDK adapter: map resolved config to `create_agent` + `stream_agent`
- [x] Input mapping (text/url/file/binary parts, content_mode file/inline)
- [x] System prompt rendering (Jinja2 template)
- [x] Execution coordinator: setup -> run -> finalize pipeline
- [x] Session commit flow: export state, compress events, write store, update PG
- [x] Deferred tool handling (awaiting_tool_results status, user_interactions, tool_results)

## Phase 4: Event Protocol and Transport

Event processing and delivery.

- [ ] Protocol event envelope model (event_id, event_type, session_id, timestamp, agent_id, payload)
- [ ] Event processor: normalize internal events to protocol events
- [ ] Event processor: buffer events during execution
- [ ] Event processor: compress events into display_messages after execution
- [ ] SSE transport (sse-starlette EventSourceResponse, terminal event closes connection)
- [ ] Redis stream transport (XADD to `nether:stream:{session_id}`, short TTL)
- [ ] Stream-to-SSE bridge (`GET /sessions/{id}/events`, `Last-Event-ID` resume)

## Phase 5: Chat API (Conversation-Level Endpoints)

High-level conversation operations.

- [ ] `POST /api/conversations/run` (new conversation or continue)
- [ ] `POST /api/conversations/{id}/fork` (fork new conversation from session)
- [ ] `POST /api/conversations/{id}/interrupt` (interrupt all active sessions)
- [ ] `POST /api/conversations/{id}/steer` (steer active agent session)
- [ ] `GET /api/conversations/{id}/events` (stream-to-SSE bridge for active session)
- [ ] `POST /api/conversations/{id}/update` (title, metadata, status, default_preset_id)
- [ ] `GET /api/conversations/{id}/turns` (display messages across sessions)
- [ ] `GET /api/conversations/{id}/sessions` (list sessions with status)
- [ ] Concurrency guard: at most one running agent session per conversation (409)

## Phase 6: Session API (Lower-Level)

Direct session control.

- [ ] `POST /api/sessions/execute` (explicit session creation and execution)
- [ ] `GET /api/sessions/{id}/get` (PG index + optional display_messages)
- [ ] `GET /api/sessions/{id}/status` (check registry then PG)
- [ ] `GET /api/sessions/{id}/events` (stream-to-SSE bridge with resume)
- [ ] `POST /api/sessions/{id}/interrupt`
- [ ] `POST /api/sessions/{id}/steer`

## Phase 7: Control (Interrupt and Steering)

In-process control via session registry.

- [ ] Interrupt handler: `registry.get()` -> `streamer.interrupt()` -> partial commit
- [ ] Steering handler: `registry.get()` -> `context.bus.send()` -> consumed at next turn
- [ ] Input mapping for steering (same format as run)

## Phase 8: Async Agents and Mailbox

Async subagent orchestration.

- [ ] `async_delegate` tool (check registry, self-call execute, update registry)
- [ ] Mailbox: post `subagent_result` / `subagent_failed` on subagent terminal state
- [ ] `POST /api/conversations/{id}/fire` (drain mailbox, render prompt, execute continuation)
- [ ] `GET /api/conversations/{id}/mailbox` (query messages with delivery status)
- [ ] Mailbox message rendering (single and multi-result templates)
- [ ] Delivery tracking (`delivered_to` prevents duplicate delivery)

## Phase 9: Authentication

- [ ] Auth middleware: validate `Authorization: Bearer {token}` on all endpoints except health
- [ ] Skip auth for `GET /api/health`

## Phase 10: Health Endpoint Enhancement

- [ ] Enrich health response with PG and Redis connectivity status

## Phase 11: Web UI

- [ ] Admin: preset list page
- [ ] Admin: preset create/edit form
- [ ] Admin: preset delete with confirmation
- [ ] Chat: conversation list
- [ ] Chat: create new conversation
- [ ] Chat: message input and send
- [ ] Chat: SSE streaming response display
- [ ] Chat: interrupt / steer controls

## Phase 12: IM Gateway

- [ ] Runtime client: HTTP wrapper for agent-runtime API
- [ ] Runtime client: SSE event consumption via bridge endpoint
- [ ] Conversation mapper: in-memory channel \<-> conversation_id cache
- [ ] Conversation mapper: recovery via metadata query on restart
- [ ] Bridge core: message flow orchestration (receive -> run -> stream -> render)
- [ ] Discord adapter: bot lifecycle, message handling, thread management
- [ ] Message rendering: protocol events -> Discord messages (chunking, formatting)

## In-Code TODOs

- `app.py` -- Flush pending mailbox messages during shutdown
- `environment.py` -- Replace LocalEnvironment with VirtualLocalEnvironment once SDK provides VirtualFileOperator
- `environment.py` -- Implement DockerShell integration for docker mode
- `runtime.py` -- Implement subagent config mapping (Phase 8)
