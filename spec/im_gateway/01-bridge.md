# 01 - Bridge Core

The bridge core orchestrates message flow between platform adapters and the agent runtime. It handles runtime communication, conversation mapping, and event-to-message rendering -- all via HTTP.

## Message Flow

### User to Agent

```mermaid
sequenceDiagram
    participant U as User
    participant PA as Platform Adapter
    participant BR as Bridge Core
    participant CM as Conversation Mapper
    participant RC as Runtime Client
    participant RT as Agent Runtime

    U->>PA: send message
    PA->>BR: on_message(channel, user, content)
    BR->>CM: resolve(platform, channel_id)

    alt Cache miss
        CM->>RC: GET /conversations/list?metadata={...}
        RC-->>CM: conversation or null
    end

    CM-->>BR: conversation_id (or null)

    alt New conversation
        BR->>RC: POST /conversations/run (new, metadata={...})
        RC-->>BR: {session_id, conversation_id, stream_key}
        BR->>CM: cache(channel_id -> conversation_id)
    else Existing conversation
        BR->>RC: POST /conversations/run (continue)
        RC-->>BR: {session_id, stream_key}
    end

    BR->>RC: GET /sessions/{session_id}/events (SSE)
    loop SSE event stream
        RC-->>BR: protocol event
        BR->>PA: render(event)
        PA->>U: platform message
    end
```

### Agent to User (Event Rendering)

```mermaid
flowchart LR
    SSE["SSE Bridge<br/>(protocol events)"] --> ACC["Content<br/>Accumulator"]
    ACC --> SPL["Message<br/>Splitter"]
    SPL --> FMT["Platform<br/>Formatter"]
    FMT --> API["Platform API<br/>(send/edit)"]
```

## Runtime Client

HTTP-only client wrapping agent-runtime API calls and SSE consumption.

### API Operations

| Operation | Runtime Endpoint                         | When                                |
| --------- | ---------------------------------------- | ----------------------------------- |
| Run       | `POST /api/conversations/run`            | User sends message                  |
| Interrupt | `POST /api/conversations/{id}/interrupt` | User requests cancellation          |
| Steer     | `POST /api/conversations/{id}/steer`     | User sends message during execution |
| Fire      | `POST /api/conversations/{id}/fire`      | Async subagent results ready        |
| Get       | `GET /api/conversations/{id}/get`        | Check conversation state            |
| Lookup    | `GET /api/conversations/list`            | Recover mapping by metadata query   |

### Event Consumption

All runs use `transport=stream`. The runtime writes events to Redis internally. The gateway consumes them through the SSE bridge endpoint, never touching Redis directly.

```mermaid
sequenceDiagram
    participant GW as Gateway
    participant RT as Runtime
    participant RD as Redis (internal)

    GW->>RT: POST /conversations/run (transport=stream)
    RT-->>GW: 202 {session_id, stream_key}

    Note over RT,RD: Runtime writes events to Redis internally

    GW->>RT: GET /sessions/{session_id}/events (SSE)

    loop SSE events (bridged from Redis)
        RT-->>GW: event: content_delta / tool_call / ...
    end

    RT-->>GW: event: run_completed (terminal)
    Note over GW: SSE connection closes
```

Benefits of this approach:

- Gateway has no Redis dependency
- SSE bridge supports `Last-Event-ID` for reconnection
- Execution is decoupled from consumption (agent runs to completion regardless of gateway connection)

### Busy Handling

When `POST /conversations/run` returns `409 Conflict` (conversation already has a running session), the gateway falls back to steering:

1. Extract `active_session` from 409 response
2. `POST /conversations/{id}/steer` with the user's message
3. Attach to active session's SSE bridge if not already consuming

If steering also fails (session completed between calls), retry as a new run.

## Conversation Mapper

In-memory cache mapping platform channels to runtime conversations. Recoverable from runtime on restart.

### Cache Structure

```
{(platform, channel_id): conversation_id}
```

### Mapping Lifecycle

```mermaid
flowchart TB
    MSG["Message from channel"] --> CACHE{"In cache?"}
    CACHE -->|Hit| USE["Use conversation_id"]
    CACHE -->|Miss| QUERY["Query runtime:<br/>GET /conversations/list<br/>?metadata={platform,thread_id}"]
    QUERY --> FOUND{"Found?"}
    FOUND -->|Yes| POPULATE["Populate cache"]
    FOUND -->|No| CREATE["New conversation:<br/>POST /conversations/run<br/>metadata={platform,thread_id}"]
    CREATE --> POPULATE
    POPULATE --> USE
```

### Mapping Rules

| Platform Context            | Metadata                               | Lifecycle                           |
| --------------------------- | -------------------------------------- | ----------------------------------- |
| Discord thread              | `{platform: discord, thread_id: ...}`  | Created when thread is first used   |
| Discord DM                  | `{platform: discord, dm_user_id: ...}` | Created on first DM                 |
| Discord channel (no thread) | N/A                                    | Bot creates thread first, then maps |

### Recovery on Restart

On gateway restart, the in-memory cache is empty. Recovery is lazy:

- Each incoming message triggers a cache lookup
- On miss, query runtime by metadata containment
- If found, re-populate cache and continue conversation
- If not found (conversation was deleted), create new conversation

No bulk recovery needed. The cache warms up naturally as users send messages.

## Event Rendering

### Content Accumulator

Collects `content_delta` events into coherent text blocks. Buffers updates and flushes to the platform adapter at a controlled rate to respect API rate limits.

| Parameter       | Description                    | Default |
| --------------- | ------------------------------ | ------- |
| flush_interval  | Min time between message edits | 1s      |
| flush_threshold | Min new chars before edit      | 100     |

### Message Splitter

Splits accumulated content at platform character limits. Preserves structure:

- Never splits inside code blocks
- Prefers splitting at paragraph boundaries
- Falls back to sentence boundaries, then hard split at limit

### Rendering Strategy

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Streaming: run_started
    Streaming --> Streaming: content_delta (edit message)
    Streaming --> Streaming: tool activity (status line)
    Streaming --> Overflow: char limit reached
    Overflow --> Streaming: new message, continue deltas
    Streaming --> Done: run_completed
    Streaming --> Error: run_failed
    Done --> Idle: finalize
    Error --> Idle: show error
```

During streaming:

1. Post an initial placeholder message
2. Edit the message as `content_delta` events arrive (rate-limited)
3. When approaching platform char limit, post a new message and continue
4. On `run_completed`, post the final clean content
5. On `run_failed`, post an error message

### Tool Call Display

Tool calls are secondary information. Rendering depends on platform capability:

| Approach      | Description                          | Platform      |
| ------------- | ------------------------------------ | ------------- |
| Inline status | Brief one-line status in the message | All           |
| Collapsed     | Expandable section with details      | Discord embed |
| Hidden        | Omitted; only final text shown       | Minimal UIs   |

Default: inline status during streaming, collapsed summary in final message.
