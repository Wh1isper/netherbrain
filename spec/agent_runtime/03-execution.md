# 03 - Execution

The execution coordinator manages a single agent run: environment setup, agent execution, event processing, and session commit.

## Execution Flow

```mermaid
sequenceDiagram
    participant C as Caller
    participant API as API Layer
    participant RES as Config Resolver
    participant EC as Execution Coordinator
    participant EP as Event Processor
    participant TP as Transport
    participant SM as Session Manager

    C->>API: POST /conversations/run
    API->>RES: resolve(preset_id, override)
    RES-->>API: ResolvedConfig

    API->>EC: run(resolved, input, parent_session?)

    Note over EC: Setup
    EC->>EC: Load parent session state (if continuing)
    EC->>EC: Map input to SDK UserPrompt
    EC->>EC: Setup environment (local or docker)
    EC->>EC: Render system prompt

    Note over EC: Agent Execution
    EC->>EC: create_agent + stream_agent
    loop Events
        EC-->>EP: internal event
        EP-->>TP: protocol event
        TP-->>C: SSE frame / Redis XADD
    end

    Note over EC: Finalize
    EC->>EP: compress()
    EP-->>EC: display_messages
    EC->>SM: commit(SDK state + display_messages)
    EC-->>C: terminal event
```

## Execution Coordinator

The coordinator wires together all components for a single run.

```mermaid
flowchart LR
    subgraph Setup
        S1["Load parent session"]
        S2["Create Environment"]
        S3["Create Event Processor"]
        S4["Create Transport"]
    end

    subgraph Execute
        E1["create_agent + stream_agent"]
        E2["Events -> Processor -> Transport"]
    end

    subgraph Finalize
        F1["compress() -> display_messages"]
        F2["Export SDK state"]
        F3["Session commit (PG + State Store)"]
    end

    Setup --> Execute --> Finalize
```

Responsibilities:

- **Setup**: Load parent state, create environment, instantiate transport
- **Execute**: Run the agent, pipe events through processor to transport
- **Finalize**: Compress events, export SDK state, commit session

Pipeline execution and transport delivery are decoupled. The agent runs to completion regardless of consumer speed or disconnection.

## Environment Setup

```mermaid
flowchart TB
    RC[Resolved Config] --> CHECK{shell_mode}
    CHECK -->|local| LOCAL["LocalEnvironment<br/>(default_path, allowed_paths)"]
    CHECK -->|docker| DOCKER["DockerShell + LocalFileOperator<br/>(container_id, workdir)"]

    LOCAL --> ENV[Environment]
    DOCKER --> ENV

    PARENT["Parent Session?"] -->|Yes| RESTORE["Restore resource_state"]
    PARENT -->|No| FRESH["Fresh environment"]

    RESTORE --> ENV
    FRESH --> ENV
```

- **Local mode**: `LocalEnvironment` with configured paths
- **Docker mode**: `LocalFileOperator` for file operations + `DockerShell` targeting the configured container. File operations remain on the host; shell commands execute inside the container via `docker exec`

When continuing a session, environment resource state is restored from the parent session's `environment_state`.

## SDK Integration

The coordinator maps resolved config to SDK primitives.

```mermaid
flowchart TB
    RC[Resolved Config] --> ADP[SDK Adapter]

    ADP --> MODEL["model_name -> Model"]
    ADP --> MCFG["model_config -> ModelConfig"]
    ADP --> TCFG["tool_config -> ToolConfig<br/>(API keys from env vars)"]
    ADP --> TS["toolsets -> Toolset instances"]
    ADP --> SP["system_prompt -> rendered string"]
    ADP --> STATE["parent session -> ResumableState"]
    ADP --> ENV["environment config -> Environment"]
    ADP --> SUB["subagent refs -> SubagentConfig[]"]

    MODEL & MCFG & TCFG & TS & SP & STATE & ENV & SUB --> CA["create_agent()"]

    ADP --> UP["input -> user_prompt"]
    ADP --> UI["user_interactions -> DeferredToolResults.approvals"]
    ADP --> TR["tool_results -> DeferredToolResults.calls"]

    UP & UI & TR --> SA["stream_agent()"]
```

## Input Mapping

Input is a list of content parts, mapped to SDK UserPrompt.

| Part Type | Description                   | Mapping                       |
| --------- | ----------------------------- | ----------------------------- |
| text      | Plain text                    | Pass through as string        |
| url       | Remote resource (image, etc.) | Download to environment       |
| file      | Local file reference          | Resolve workspace path        |
| binary    | Base64-encoded content        | Write to environment temp dir |

Input mapping uses `user_prompt_factory` for lazy execution at agent start time.

### Deferred Tool Feedback

When continuing from a session with status `awaiting_tool_results`:

| Request Field       | SDK Target                      | Semantics                        |
| ------------------- | ------------------------------- | -------------------------------- |
| `user_interactions` | `DeferredToolResults.approvals` | HITL approval (tool re-executes) |
| `tool_results`      | `DeferredToolResults.calls`     | External result provided         |

Pending deferred tools not covered by feedback are auto-denied/auto-failed.

## Session Commit

After execution completes:

1. Export `context_state` and `message_history` from SDK
2. Export `environment_state` from Environment
3. Compress protocol events into `display_messages`
4. Write `state.json` and `display_messages.json` to State Store
5. Update PG session index (status -> committed, run_summary)

If state write fails, session status is set to `failed`. Display messages failure is non-fatal (session is still restorable).
