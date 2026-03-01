# 01 - Conversation and Session

Two core data models. **Conversations** group related agent interactions. **Sessions** are immutable snapshots linked in a git-like DAG within a conversation.

## Git-like DAG

Each session is a commit. `parent_session_id` forms the history chain.

```mermaid
flowchart LR
    S0((S0)) -->|continue| S1((S1))
    S1 -->|continue| S2((S2))
    S1 -->|fork| S3((S3))
    S3 -->|continue| S4((S4))
```

- **Continue**: New session with parent pointing to previous session
- **Fork**: New session with parent pointing to any historical session (starts new conversation)
- **Root**: Session with no parent (new conversation)

Sessions are never mutated after commit. A new execution always produces a new session_id.

## Session Structure

| Field             | Store       | Type               | Description                                                     |
| ----------------- | ----------- | ------------------ | --------------------------------------------------------------- |
| session_id        | PG          | string (immutable) | Unique snapshot identity                                        |
| parent_session_id | PG          | string?            | Previous snapshot (null for root)                               |
| project_ids       | PG          | list[string]       | Ordered project references for this session's environment       |
| status            | PG          | enum               | created / committed / awaiting_tool_results / failed / archived |
| run_summary       | PG          | RunSummary         | Run metadata captured at commit time                            |
| input             | PG          | list[Part]?        | API input parts (written at creation)                           |
| final_message     | PG          | string?            | Final model text output (written at commit)                     |
| metadata          | PG          | SessionMetadata    | Indexed fields for query and attribution                        |
| created_at        | PG          | timestamp          | Snapshot creation time                                          |
| context_state     | State Store | JSON               | SDK ResumableState (subagent history, handoff, usages)          |
| message_history   | State Store | JSON               | LLM message history (pydantic-ai ModelMessage sequence)         |
| environment_state | State Store | JSON               | Environment resource state for restore                          |

### Input Parts

Input is a list of content parts, stored as JSONB on the session row. Each part has a `type` and optional `mode` to control delivery.

| Field | Type    | Required | Description                            |
| ----- | ------- | -------- | -------------------------------------- |
| type  | enum    | Yes      | `text` / `url` / `file` / `binary`     |
| text  | string  | Cond.    | Text content (type=text)               |
| url   | string  | Cond.    | Resource URL (type=url)                |
| path  | string  | Cond.    | Project-relative file path (type=file) |
| data  | string  | Cond.    | Base64-encoded content (type=binary)   |
| mime  | string? | No       | MIME type hint (for url/binary)        |
| mode  | enum?   | No       | Per-part delivery: `file` / `inline`   |

See [03-execution.md](03-execution.md) for input mapping behavior.

## Run Summary

Captured at commit time. Persisted in PG index for queryability.

| Field       | Type         | Description                  |
| ----------- | ------------ | ---------------------------- |
| duration_ms | int          | Run duration in milliseconds |
| usage       | UsageSummary | Aggregated token usage       |

### UsageSummary

| Field             | Type | Description               |
| ----------------- | ---- | ------------------------- |
| total_tokens      | int  | Total tokens consumed     |
| prompt_tokens     | int  | Input tokens              |
| completion_tokens | int  | Output tokens             |
| model_requests    | int  | Number of model API calls |

## Session Metadata

Indexed fields stored in PG for query.

| Field           | Type    | Mutable | Description                                     |
| --------------- | ------- | ------- | ----------------------------------------------- |
| session_type    | enum    | No      | `agent` / `async_subagent`                      |
| transport       | enum    | No      | `sse` / `stream`                                |
| conversation_id | string  | No      | Conversation identifier (= session_id for root) |
| spawned_by      | string? | No      | Session that dispatched this async subagent     |
| preset_id       | string? | No      | Agent preset used                               |

`conversation_id` is always set at creation time:

| Scenario       | conversation_id           |
| -------------- | ------------------------- |
| Root           | = session_id              |
| Continuation   | = parent.conversation_id  |
| Fork           | = session_id (new)        |
| Async subagent | = spawner.conversation_id |

## Conversation

A conversation is a logical collection of sessions sharing a `conversation_id`. Backed by a lightweight index table in PostgreSQL.

### Conversation Index

| Field             | Type      | Mutable | Description                                 |
| ----------------- | --------- | ------- | ------------------------------------------- |
| conversation_id   | string    | No      | Primary key                                 |
| title             | string?   | Yes     | Conversation title                          |
| default_preset_id | string?   | Yes     | Default agent preset                        |
| metadata          | JSONB     | Yes     | Client-defined metadata (opaque to runtime) |
| status            | enum      | Yes     | active / archived                           |
| created_at        | timestamp | No      | Creation time                               |
| updated_at        | timestamp | Yes     | Last activity time                          |

| Aspect      | Scope                                                                                  |
| ----------- | -------------------------------------------------------------------------------------- |
| Concurrency | At most one running `session_type=agent` session per conversation                      |
| Environment | Each session snapshots its own `project_ids`; continue inherits from parent by default |

### Conversation Turns

A conversation's turns are the sequence of input/output pairs across its committed sessions. Retrieved directly from PG (no state store access needed).

```mermaid
flowchart LR
    subgraph Conversation
        S0["Session 0<br/>input: [text: 'hello']<br/>final: 'Hi!'"]
        S1["Session 1<br/>input: [text: 'help me']<br/>final: 'Sure...'"]
        S0 --> S1
    end
```

## Dual Storage Model

LLM context (for SDK restore) and display data (for callers) are stored separately.

```mermaid
flowchart TB
    subgraph PG["PostgreSQL (queryable, lightweight)"]
        IDX["Session Index<br/>(status, run_summary, metadata)"]
        IO["Display Data<br/>(input, final_message)"]
    end
    subgraph Store["State Store (heavy, immutable)"]
        SDK["state.json<br/>(context_state, message_history,<br/>environment_state)"]
    end
```

- **State Store** (`state.json`): SDK resumable state packed as a single blob. Used to restore agent state for the next turn. Not for caller consumption. Single-file write ensures atomicity on both local FS (tempfile + rename) and S3 (single PUT).
- **PG Display Data** (`input` + `final_message`): Lightweight text fields for conversation rendering, search, and IM message formatting.

## Persistence Topology

```mermaid
flowchart LR
    subgraph RT["Runtime Service"]
        SM[Session Manager]
    end

    subgraph PG["PostgreSQL"]
        IDX["Session Index<br/>(id, parent_id, project_ids,<br/>status, run_summary, metadata,<br/>input, final_message)"]
        CONV["Conversation Index<br/>(conversation_id, title,<br/>status)"]
    end

    subgraph Store["State Store (Local FS / S3)"]
        STATE["state.json<br/>(context_state, message_history,<br/>environment_state)"]
    end

    SM -->|"index + display"| IDX
    SM -->|"conversation metadata"| CONV
    SM -->|"SDK state read/write"| STATE
```

| Store       | What                                  | Why                                    |
| ----------- | ------------------------------------- | -------------------------------------- |
| PG          | Session index, input, final_message   | Queryable lineage, display, search     |
| State Store | context_state + message_history + env | Large opaque blob, single atomic write |

### Storage Layout

Local filesystem (default):

```
{data_dir}/sessions/{session_id}/state.json
```

S3 (optional):

```
{bucket}/sessions/{session_id}/state.json
```

## Session Lifecycle

### Session Status (PG)

```mermaid
stateDiagram-v2
    [*] --> created: execution starts
    created --> committed: execution succeeds
    created --> awaiting_tool_results: output = DeferredToolRequests
    created --> failed: execution fails or interrupted
    committed --> archived: soft delete
```

| Status                | Meaning                                        |
| --------------------- | ---------------------------------------------- |
| created               | Execution started, PG index exists             |
| committed             | State written, session is complete             |
| awaiting_tool_results | Committed with deferred tools pending feedback |
| failed                | Execution failed, no state written             |
| archived              | Soft deleted                                   |

### Session Registry (In-Process)

An in-memory registry tracks active sessions. It holds live object references for direct control (interrupt, steering) and serves as the authoritative "is this session running?" index.

| Field      | Type          | Description                            |
| ---------- | ------------- | -------------------------------------- |
| session_id | string        | Registry key                           |
| streamer   | AgentStreamer | Live reference for interrupt           |
| context    | AgentContext  | Live reference for steering (bus.send) |
| stream_key | string?       | Redis stream key (if transport=stream) |

The registry is ephemeral. On process restart, it is empty. All durable metadata lives in PG.

### Startup Recovery

On startup, the runtime scans PG for sessions with `status = created` (orphaned by a previous crash) and marks them as `failed`. This ensures PG and the empty registry are consistent.
