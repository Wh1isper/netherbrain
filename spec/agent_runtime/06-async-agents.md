# 06 - Async Agents

Agent classification based on delivery mode and invocation origin. Four agent types, with async subagent as the key extension requiring orchestration support.

## Agent Taxonomy

Two axes: delivery (sync/async) and invocation (main/subagent).

```mermaid
quadrantChart
    title Agent Types
    x-axis "Main Agent" --> "Subagent"
    y-axis "Sync (SSE)" --> "Async (Stream)"
    "Sync Agent": [0.2, 0.2]
    "Async Agent": [0.2, 0.8]
    "Sync Subagent": [0.8, 0.2]
    "Async Subagent": [0.8, 0.8]
```

| Type           | Transport    | Initiated by | Session          | Description                            |
| -------------- | ------------ | ------------ | ---------------- | -------------------------------------- |
| Sync Agent     | SSE          | Caller       | Own              | Standard request-response              |
| Async Agent    | Redis Stream | Caller       | Own              | Detachable, caller attaches at will    |
| Sync Subagent  | Parent's     | Parent agent | In parent        | Inline execution within parent (SDK)   |
| Async Subagent | Redis Stream | Orchestrator | Own, independent | Parallel execution, result via mailbox |

### Sync Agent

Caller sends `POST /conversations/run` with `transport=sse`, blocks on SSE until agent completes.

### Async Agent

Same as sync agent but with `transport=stream`. Events flow through Redis Stream; caller can attach/detach/reattach. Architecturally identical -- only the transport differs.

### Sync Subagent

Existing SDK model. Parent calls `delegate` tool; subagent runs inline as nested `Agent.iter()`. No separate session. Invisible to the runtime service.

### Async Subagent

Independent execution with its own session. Spawned by the `async_delegate` tool. Result delivered back via conversation mailbox.

| Aspect          | Sync Subagent              | Async Subagent                  |
| --------------- | -------------------------- | ------------------------------- |
| Execution       | Inline within parent       | Independent, own execution      |
| Session         | No (state in parent)       | Yes, own session                |
| Concurrency     | Sequential (blocks parent) | Parallel (parent continues)     |
| Result delivery | Tool return value          | Mailbox message in continuation |
| Environment     | Shares parent in-process   | Shares via environment state    |

## Orchestration

```mermaid
flowchart TB
    subgraph OL["Orchestration Layer"]
        GM["Session Metadata<br/>(conversation_id, spawned_by)"]
        MB["Conversation Mailbox<br/>(collect outcomes)"]
        FL["Fire Logic<br/>(drain mailbox + create continuation)"]
    end

    subgraph EL["Execution Layer (unchanged)"]
        EX["Execution Coordinator"]
        SC["Session Commit"]
    end

    OL -->|"continuation with rendered prompt"| EX
    SC -->|"async_subagent terminal state"| MB
    FL -->|"drain"| MB
    FL -->|"create continuation"| EX
```

The orchestration layer relates, collects, and bridges. The execution layer is unchanged -- async subagents go through the identical execution path as any other run.

## Lifecycle

```mermaid
sequenceDiagram
    participant C as Caller
    participant RT as Runtime
    participant MB as Mailbox

    C->>RT: POST /conversations/run (transport=stream)
    RT->>RT: R1 starts

    Note over RT: Agent calls async_delegate tool
    RT->>RT: Self-call: execute subagent
    Note over RT: R2 (subagent) starts in parallel

    RT->>RT: R1 completes, commit S1

    Note over C: User continues chatting
    C->>RT: POST /conversations/run (conversation_id=C1)
    RT->>RT: S5 commits

    RT->>RT: R2 completes, commit S2
    RT->>MB: Post subagent_result (source=S2)

    Note over C: Client fires when ready
    C->>RT: POST /conversations/{id}/fire
    RT->>RT: Resolve latest agent session = S5
    RT->>MB: Drain undelivered messages
    RT->>RT: Render mailbox + input into prompt
    RT->>RT: Execute continuation (parent=S5)
    RT->>RT: S6 commits
    RT->>MB: Mark delivered_to = S6
    RT-->>C: {session_id: S6}
```

## Session Creation Matrix

| Scenario                | parent_session_id  | session_type   | conversation_id           | spawned_by |
| ----------------------- | ------------------ | -------------- | ------------------------- | ---------- |
| Root                    | null               | agent          | = session_id              | null       |
| Continuation            | = previous session | agent          | = parent.conversation_id  | null       |
| Fork                    | = historical       | agent          | = session_id (new)        | null       |
| Async subagent (fresh)  | null               | async_subagent | = spawner.conversation_id | = spawner  |
| Async subagent (resume) | = prev sub session | async_subagent | = parent.conversation_id  | = spawner  |

## Conversation Mailbox

Persistent message store (PostgreSQL) collecting subagent outcomes within a conversation.

### MailboxMessage

| Field             | Type      | Description                                 |
| ----------------- | --------- | ------------------------------------------- |
| message_id        | string    | Unique identifier                           |
| conversation_id   | string    | Owning conversation                         |
| source_session_id | string    | Session that produced the outcome           |
| source_type       | enum      | `subagent_result` / `subagent_failed`       |
| subagent_name     | string    | Display name                                |
| created_at        | timestamp | When posted                                 |
| delivered_to      | string?   | Session that consumed this (null = pending) |

Messages are lightweight references. Full content is retrieved from the source session's `display_messages` at render time.

### Production Rules

| Event                    | source_type     |
| ------------------------ | --------------- |
| Subagent session commits | subagent_result |
| Subagent execution fails | subagent_failed |

### Delivery Tracking

`delivered_to` prevents duplicate delivery. A fire operation atomically drains all pending messages and marks them with the new session's ID.

## Fire Logic (Manual Only)

Client explicitly fires via `POST /conversations/{conversation_id}/fire`.

```mermaid
flowchart TB
    FIRE["POST /conversations/{cid}/fire"] --> P["1. Resolve parent:<br/>latest committed agent session"]
    P --> D["2. Drain mailbox:<br/>undelivered messages"]
    D --> R["3. Render prompt:<br/>mailbox + optional input"]
    R --> E["4. Execute continuation<br/>(parent=resolved)"]
    E --> M["5. Mark delivered"]
```

Rejects with `422` if mailbox is empty.

### Message Rendering

Single result:

```
Async subagent '{name}' (session: {id}) completed:
{display_messages content}
```

Multiple results:

```
Async subagent results:

## {name_1} [completed] (session: {id_1})
{result_1}

## {name_2} [failed] (session: {id_2})
Error: {error_2}
```

## Async Delegate Tool

Available when the agent preset enables async subagents.

1. Read `async_subagent_registry` from AgentContext to check for existing subagent
2. Self-call: execute subagent session (subagent preset, `transport=stream`, same `conversation_id`)
3. Write dispatch info to registry
4. Return: "Task dispatched to '{name}' (session: {session_id})"

Resume: if registry has an existing session for the subagent name, the new execution continues from that session (`parent_session_id = previous`).

## Fan-out / Fan-in

```mermaid
flowchart LR
    S1((S1)) -->|spawn| S2((S2))
    S1 -->|spawn| S4((S4))
    S2 -.->|result| MB[mailbox]
    S4 -.->|result| MB
    MB -.->|"fire once,<br/>drain all"| S6((S6))
    S1 -->|parent| S6
```

Client can wait for all subagents, then fire once. All mailbox messages drain into a single continuation prompt.

## Failure Handling

| Scenario                        | Behavior                                    |
| ------------------------------- | ------------------------------------------- |
| Subagent fails                  | Failed message posted to mailbox            |
| Main agent fails after dispatch | Subagents continue; results land in mailbox |
| Fire with empty mailbox         | Rejected (422)                              |
| Interrupted subagent            | Partial commit = result; no commit = failed |

No automatic cascading interrupt. Main agent failure does not kill running subagents.
