# 02 - Chat

## Message Thread

Messages are displayed in a vertical thread. User messages and agent responses are visually distinct through alignment, background color, and icons.

### Message Types

| Type           | Visual                                        |
| -------------- | --------------------------------------------- |
| User message   | Right-aligned or full-width with user icon    |
| Agent response | Left-aligned or full-width with agent icon    |
| System notice  | Centered, muted text (errors, status changes) |

### Agent Response Rendering

Agent responses are rendered from two sources:

- **Streaming**: SSE protocol events (`content_delta`, `tool_call_start`, etc.) during live execution.
- **History**: `input` / `final_message` pairs loaded via `GET /conversations/{id}/turns` for completed sessions.

```mermaid
flowchart TB
    subgraph Response["Agent Response Block"]
        TEXT["Markdown text<br/>(prose, headings, lists)"]
        CODE["Code blocks<br/>(syntax highlight + copy)"]
        TOOL["Tool call cards<br/>(collapsible)"]
        THINK["Thinking section<br/>(collapsed by default)"]
    end
```

#### Markdown

Full CommonMark rendering with GFM extensions (tables, task lists, strikethrough). Code blocks use Shiki for syntax highlighting with theme-aware colors.

Each code block has:

- Language label (top-left)
- Copy button (top-right)

#### Tool Calls

Displayed as compact collapsible cards inline with the message flow.

Collapsed state: single line showing tool name and brief summary.

```
> Used shell: npm test (exit 0)
```

Expanded state: shows arguments and full output (scrollable, max height capped).

#### Thinking

Agent reasoning/thinking content is rendered in a collapsed section with muted styling. Click to expand. Hidden entirely if empty.

## Streaming

During agent execution, the response streams in real-time via SSE.

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Streaming: send message
    Streaming --> Streaming: content_delta
    Streaming --> ToolRunning: tool_call_start
    ToolRunning --> Streaming: tool_call_end
    Streaming --> Done: run_completed
    Streaming --> Error: run_failed
    Done --> Idle
    Error --> Idle
```

### Streaming Behavior

- Text appears incrementally (character/chunk level)
- Auto-scroll follows new content unless user has scrolled up
- Tool calls appear as "running" cards, then resolve with results
- Cursor/typing indicator shown at end of streaming text

### Connection

Chat page uses stream transport (`transport=stream`) for resilient streaming backed by Redis Streams. On connection drop, the UI reconnects automatically with no event loss.

Fallback: when Redis is not configured (422 from server), the UI retries with `transport=sse` for direct streaming without reconnection support.

```mermaid
sequenceDiagram
    participant UI
    participant API
    participant Redis

    UI->>API: POST /conversations/run (transport=stream)
    API-->>UI: 202 {conversation_id, stream_key}
    API->>Redis: XADD events

    UI->>API: GET /conversations/{id}/events
    API->>Redis: XREAD
    Redis-->>API: events
    API-->>UI: SSE stream (id: stream-entry-id)

    Note over UI,API: Connection drops

    UI->>API: GET /conversations/{id}/events<br/>Last-Event-ID: stream-entry-id
    API->>Redis: XREAD from cursor
    Redis-->>API: missed events
    API-->>UI: SSE stream resumes
```

#### Reconnection behavior

| Scenario                         | Action                                           |
| -------------------------------- | ------------------------------------------------ |
| Stream drops, session running    | Reconnect with `Last-Event-ID` (up to 3 times)   |
| Retries exhausted, session done  | Reload turns via `GET /conversations/{id}/turns` |
| Retries exhausted, session alive | Show "connection lost" error                     |
| Bridge returns 404               | Session finished; reload turns                   |
| Bridge returns 410               | Stream expired; reload turns                     |
| 409 Conversation busy            | Reattach to existing stream via bridge           |

#### Reattach on navigation

When loading an existing conversation (`/c/:id`) that has an active stream session, the UI loads turn history first, then reattaches to the live stream via `GET /conversations/{id}/events`.

## Input Area

Pinned to the bottom of the chat view.

```mermaid
flowchart LR
    subgraph Input["Input Area"]
        TA["Auto-resize textarea"]
        SEND["Send button"]
    end
```

### States

| State     | Send Button | Textarea        | Extra Controls |
| --------- | ----------- | --------------- | -------------- |
| Idle      | Send        | Enabled         | None           |
| Streaming | Stop        | Enabled (steer) | None           |
| Empty     | Disabled    | Enabled         | None           |

### Send Behavior

- **Idle**: POST `/api/conversations/run`, start SSE stream
- **Streaming + Send**: POST `/api/conversations/{id}/steer` (inject guidance)
- **Stop**: POST `/api/conversations/{id}/interrupt`

### Keyboard

- `Enter`: Send message
- `Shift+Enter`: New line
- `Escape`: Cancel input / close panels

## Conversation Header

Shown at top of the chat area.

| Element      | Description                                                               |
| ------------ | ------------------------------------------------------------------------- |
| Title        | Editable conversation title (saved via `POST /conversations/{id}/update`) |
| Preset badge | Shows which agent preset is active                                        |
| Actions menu | Fork, change preset, archive (status update via same endpoint)            |

## Loading History

When the user opens an existing conversation (sidebar click or direct navigation to `/c/:id`):

1. Fetch conversation metadata: `GET /conversations/{id}/get`
2. Fetch turn history: `GET /conversations/{id}/turns`
3. Render each turn as a user message (`input`) followed by an agent response (`final_message`)
4. If a session is still running, reattach to its SSE stream via `GET /conversations/{id}/events`

Turns are returned in chronological order. Each turn contains `session_id`, `input` (list of content parts), `final_message` (markdown string or null for in-progress turns), and `created_at`.

## New Chat

Clicking "+ New Chat" in the sidebar:

1. Resets chat state (clears messages, project selection)
2. Focus moves to the input area
3. User optionally selects projects to mount from the workspace's project pool
4. First message triggers `POST /api/conversations/run` with `project_ids` and `metadata.workspace_id`
5. Workspace's default preset is used (or system default)

## Project Selection

Workspaces define a pool of available projects (filesystem paths). Users choose which projects to mount per conversation.

```mermaid
flowchart LR
    WS["Workspace<br/>(project pool)"] --> SEL["User Selection<br/>(0..N projects)"]
    SEL --> RUN["POST /conversations/run<br/>project_ids=[...]"]
    RUN --> AGENT["Agent CWD = first project"]
```

### Behavior

| Scenario             | project_ids sent       | Agent behavior                  |
| -------------------- | ---------------------- | ------------------------------- |
| No projects selected | `[]`                   | Pure conversation mode (no CWD) |
| One project selected | `["/path/to/project"]` | CWD = that project              |
| Multiple selected    | `["/a", "/b", "/c"]`   | CWD = first, all are accessible |

### UI

- **Project selector**: Shown above the input area when workspace has projects. Each project is a toggleable chip. First selected project shows a "cwd" indicator.
- **Conversation header**: Shows mounted projects as read-only badges.
- **Default**: No projects selected (pure conversation mode).
- **Existing conversations**: Project selection is restored from `latest_session.project_ids`. User can change selection before sending the next message.
- **During streaming**: Project selector is disabled.

### Data Flow

- `workspace_id` is stored only in conversation metadata (for sidebar filtering). It is NOT sent as a top-level field in the run request.
- `project_ids` is always sent explicitly in the run request, reflecting the user's selection.

## Conversation Lifecycle

```mermaid
flowchart TB
    NEW["+ New Chat"] --> SEND["User sends message"]
    SEND --> RUN["POST /conversations/run<br/>(new conversation)"]
    RUN --> STREAM["SSE: streaming response"]
    STREAM --> DONE["Response complete"]
    DONE --> NEXT["User sends next message"]
    NEXT --> CONTINUE["POST /conversations/run<br/>(conversation_id = existing)"]
    CONTINUE --> STREAM
```
