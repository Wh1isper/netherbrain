import { create } from "zustand";
import {
  parseSSEStream,
  EventType,
  type AGUIEvent,
  type RunStartedEvent,
  type RunErrorEvent,
  type TextMessageContentEvent,
  type ReasoningMessageContentEvent,
  type ToolCallStartEvent,
  type ToolCallArgsEvent,
  type ToolCallResultEvent,
} from "../lib/sse";
import {
  runConversation,
  getConversation,
  getConversationTurns,
  interruptConversation,
  steerConversation,
  streamConversationEvents,
  updateConversation,
} from "../api/conversations";
import type {
  ConversationRunRequest,
  InputPart,
  TurnResponse,
  DisplayEvent,
  TextMessageChunk,
  ToolCallChunk,
  ToolCallResultDisplay,
  ReasoningMessageChunk,
} from "../api/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Number of turns to load per page. */
const TURNS_PAGE_SIZE = 20;

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

export interface ToolCall {
  id: string;
  name: string;
  args: string;
  result?: string;
  status: "running" | "complete" | "retry" | "cancel";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking: string;
  toolCalls: ToolCall[];
  isStreaming: boolean;
  /** Non-text input parts (images, files, URLs) for display. */
  attachments: InputPart[];
  /** Source session ID for pagination cursor (set for history-loaded messages). */
  sessionId?: string;
}

export type StreamingState = "idle" | "connecting" | "streaming" | "error";

export type ProjectSelectionSource = "default" | "session" | "user";

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

interface ChatState {
  conversationId: string | null;
  messages: ChatMessage[];
  streamingState: StreamingState;
  error: string | null;

  /** Whether older turns exist beyond what is currently loaded. */
  hasMoreMessages: boolean;
  /** True while fetching older turns (scroll-up pagination). */
  loadingMore: boolean;

  /** Selected project paths to mount (order matters: first = CWD). */
  selectedProjectIds: string[];
  /** How the current selection was set (for UI hints). */
  projectSelectionSource: ProjectSelectionSource;
  /** Update project selection. */
  setSelectedProjectIds: (ids: string[]) => void;

  /** Mailbox pending message count for the current conversation. */
  mailboxCount: number;

  /** Archive the current conversation. */
  archiveConversation: () => Promise<void>;

  /** Load an existing conversation's turn history. */
  loadConversation: (id: string) => Promise<void>;

  /** Load older turns when scrolling up. */
  loadMoreMessages: () => Promise<void>;

  /** Send a message (new conversation or continue existing). */
  sendMessage: (
    text: string,
    opts: { workspaceId: string; presetId?: string },
    attachments?: InputPart[],
  ) => Promise<void>;

  /** Interrupt the running agent. */
  interrupt: () => Promise<void>;

  /** Inject steering guidance into the running agent. */
  steer: (text: string) => Promise<void>;

  /** Reset chat state (abort any active stream). */
  clearChat: () => void;

  // Internal -- not for direct use by components
  _abortController: AbortController | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Update the last streaming assistant message in the array. */
function updateLastAssistant(
  messages: ChatMessage[],
  updater: (msg: ChatMessage) => ChatMessage,
): ChatMessage[] {
  // Find the last assistant message that is still streaming
  let idx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant" && messages[i].isStreaming) {
      idx = i;
      break;
    }
  }
  if (idx === -1) return messages;
  const updated = [...messages];
  updated[idx] = updater(updated[idx]);
  return updated;
}

/** Convert a turn's display_messages events into a ChatMessage with full detail. */
function displayEventsToMessage(sessionId: string, events: DisplayEvent[]): ChatMessage {
  let content = "";
  let thinking = "";
  const toolCalls: ToolCall[] = [];

  for (const evt of events) {
    switch (evt.type) {
      case "TEXT_MESSAGE_CHUNK": {
        const e = evt as TextMessageChunk;
        content += e.delta;
        break;
      }
      case "REASONING_MESSAGE_CHUNK": {
        const e = evt as ReasoningMessageChunk;
        thinking += e.delta;
        break;
      }
      case "TOOL_CALL_CHUNK": {
        const e = evt as ToolCallChunk;
        toolCalls.push({
          id: e.toolCallId,
          name: e.toolCallName,
          args: e.delta,
          status: "complete",
        });
        break;
      }
      case "TOOL_CALL_RESULT": {
        const e = evt as ToolCallResultDisplay;
        const existing = toolCalls.find((tc) => tc.id === e.toolCallId);
        if (existing) {
          existing.result = e.content;
          existing.status =
            e.status === "retry" ? "retry" : e.status === "cancel" ? "cancel" : "complete";
        }
        break;
      }
      // CUSTOM events are ignored for display purposes
    }
  }

  return {
    id: `${sessionId}-assistant`,
    role: "assistant",
    content,
    thinking,
    toolCalls,
    isStreaming: false,
    attachments: [],
    sessionId,
  };
}

/** Convert turn history into ChatMessage array.
 *
 * Uses display_messages for full detail (thinking, tool calls) when
 * available; falls back to final_message for text-only display.
 */
function turnsToMessages(turns: TurnResponse[]): ChatMessage[] {
  const messages: ChatMessage[] = [];

  for (const turn of turns) {
    // User message from input parts
    if (turn.input?.length) {
      const textParts = turn.input.filter((p) => p.type === "text" && p.text).map((p) => p.text!);
      const attachments = turn.input.filter((p) => p.type !== "text");
      if (textParts.length > 0 || attachments.length > 0) {
        messages.push({
          id: `${turn.session_id}-user`,
          role: "user",
          content: textParts.join("\n"),
          thinking: "",
          toolCalls: [],
          isStreaming: false,
          attachments,
          sessionId: turn.session_id,
        });
      }
    }

    // Assistant response: prefer display_messages for full detail
    if (turn.display_messages?.length) {
      messages.push(displayEventsToMessage(turn.session_id, turn.display_messages));
    } else if (turn.final_message !== null && turn.final_message !== undefined) {
      messages.push({
        id: `${turn.session_id}-assistant`,
        role: "assistant",
        content: turn.final_message,
        thinking: "",
        toolCalls: [],
        isStreaming: false,
        attachments: [],
        sessionId: turn.session_id,
      });
    }
  }

  return messages;
}

/** Create a blank user ChatMessage. */
function makeUserMessage(text: string, attachments: InputPart[] = []): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role: "user",
    content: text,
    thinking: "",
    toolCalls: [],
    isStreaming: false,
    attachments,
  };
}

/** Create a blank streaming assistant ChatMessage. */
function makeAssistantPlaceholder(): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "",
    thinking: "",
    toolCalls: [],
    isStreaming: true,
    attachments: [],
  };
}

// ---------------------------------------------------------------------------
// SSE event handler
// ---------------------------------------------------------------------------

type StoreGet = () => ChatState;
type StoreSet = (updater: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void;

function handleEvent(event: AGUIEvent, _get: StoreGet, set: StoreSet): void {
  switch (event.type) {
    case EventType.RUN_STARTED: {
      const e = event as RunStartedEvent;
      set({ conversationId: e.threadId, streamingState: "streaming" });
      break;
    }

    case EventType.TEXT_MESSAGE_CONTENT: {
      const e = event as TextMessageContentEvent;
      set((state) => ({
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          content: msg.content + e.delta,
        })),
      }));
      break;
    }

    case EventType.REASONING_MESSAGE_CONTENT: {
      const e = event as ReasoningMessageContentEvent;
      set((state) => ({
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          thinking: msg.thinking + e.delta,
        })),
      }));
      break;
    }

    case EventType.TOOL_CALL_START: {
      const e = event as ToolCallStartEvent;
      set((state) => ({
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          toolCalls: [
            ...msg.toolCalls,
            {
              id: e.toolCallId,
              name: e.toolCallName,
              args: "",
              status: "running" as const,
            },
          ],
        })),
      }));
      break;
    }

    case EventType.TOOL_CALL_ARGS: {
      const e = event as ToolCallArgsEvent;
      set((state) => ({
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          toolCalls: msg.toolCalls.map((tc) =>
            tc.id === e.toolCallId ? { ...tc, args: tc.args + e.delta } : tc,
          ),
        })),
      }));
      break;
    }

    case EventType.TOOL_CALL_RESULT: {
      const e = event as ToolCallResultEvent;
      const status =
        e.status === "retry"
          ? ("retry" as const)
          : e.status === "cancel"
            ? ("cancel" as const)
            : ("complete" as const);
      set((state) => ({
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          toolCalls: msg.toolCalls.map((tc) =>
            tc.id === e.toolCallId ? { ...tc, result: e.content, status } : tc,
          ),
        })),
      }));
      break;
    }

    case EventType.RUN_FINISHED: {
      set((state) => ({
        streamingState: "idle" as const,
        _abortController: null,
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          isStreaming: false,
        })),
      }));
      break;
    }

    case EventType.RUN_ERROR: {
      const e = event as RunErrorEvent;
      set((state) => ({
        streamingState: "error" as const,
        error: e.message || "Agent run failed",
        _abortController: null,
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          isStreaming: false,
        })),
      }));
      break;
    }

    // TEXT_MESSAGE_START/END, REASONING_START/END, TOOL_CALL_END, CUSTOM
    // are structural/lifecycle events -- no state mutation needed.
    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// Stream consumption helpers
// ---------------------------------------------------------------------------

/**
 * Consume events from a bridge SSE endpoint with automatic reconnection.
 *
 * Connects to `GET /conversations/{id}/events`, parses SSE events, and
 * reconnects with `Last-Event-ID` on connection drop.  Falls back to
 * loading turn history when retries are exhausted or the stream expires.
 */
async function consumeBridge(
  conversationId: string,
  signal: AbortSignal,
  get: StoreGet,
  set: StoreSet,
  maxRetries: number = 3,
): Promise<void> {
  let lastEventId: string | null = null;
  let retries = 0;

  while (!signal.aborted && retries <= maxRetries) {
    try {
      const response = await streamConversationEvents(conversationId, {
        lastEventId: lastEventId ?? undefined,
        signal,
      });

      if (!response.ok) {
        // 404: no active session (finished), 410: stream expired
        if (response.status === 404 || response.status === 410) {
          await recoverFromTurns(conversationId, get, set);
          return;
        }
        throw new Error(`Bridge error: HTTP ${response.status}`);
      }

      // Reset retry count on successful connection
      retries = 0;

      // Consume events (throws on connection drop)
      for await (const event of parseSSEStream(response, signal, (id) => {
        lastEventId = id;
      })) {
        if (signal.aborted) return;
        handleEvent(event, get, set);
      }

      // Stream ended -- check if we received a terminal event
      if (get().streamingState !== "streaming") {
        return; // Terminal event received, done
      }

      // Stream closed without terminal event -- connection dropped
      retries++;
    } catch {
      if (signal.aborted) return;
      retries++;
    }

    // Wait before retry (capped exponential backoff)
    if (retries <= maxRetries && !signal.aborted) {
      await new Promise((r) => setTimeout(r, Math.min(1000 * retries, 3000)));
    }
  }

  // Exhausted retries -- recover from turn history
  if (!signal.aborted) {
    await recoverFromTurns(conversationId, get, set);
  }
}

/**
 * Consume events from a direct SSE response (transport=sse fallback).
 *
 * No reconnection support -- if the connection drops, the stream is lost
 * and the error is propagated to the caller.
 */
async function consumeDirectSSE(
  body: ConversationRunRequest,
  signal: AbortSignal,
  get: StoreGet,
  set: StoreSet,
): Promise<void> {
  const response = await runConversation(body);

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errBody = await response.json();
      if (errBody?.detail) detail = String(errBody.detail);
    } catch {
      // ignore parse failure
    }
    throw new Error(detail);
  }

  for await (const event of parseSSEStream(response, signal)) {
    if (signal.aborted) break;
    handleEvent(event, get, set);
  }
}

/**
 * Recover by loading committed turn history with display_messages.
 *
 * Used when the bridge stream is lost and cannot be resumed.
 * Replaces all messages with the persisted turn history.
 */
async function recoverFromTurns(
  conversationId: string,
  get: StoreGet,
  set: StoreSet,
): Promise<void> {
  try {
    // Check if session is still active (might still be running)
    const detail = await getConversation(conversationId);
    if (detail.active_session) {
      // Agent is still running but we lost the stream -- show error
      set((state) => ({
        streamingState: "error",
        error: "Connection lost while the agent is still running. Refresh to see the result.",
        _abortController: null,
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          isStreaming: false,
        })),
      }));
      return;
    }

    // Session completed -- load final turn history with display messages
    const { turns, has_more } = await getConversationTurns(conversationId, {
      includeDisplay: true,
      limit: TURNS_PAGE_SIZE,
    });
    set({
      messages: turnsToMessages(turns),
      hasMoreMessages: has_more,
      streamingState: "idle",
      error: null,
      _abortController: null,
    });
  } catch {
    set((state) => ({
      streamingState: "error",
      error: "Connection lost. Refresh to see the result.",
      _abortController: null,
      messages: updateLastAssistant(state.messages, (msg) => ({
        ...msg,
        isStreaming: false,
      })),
    }));
  }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useChatStore = create<ChatState>()((set, get) => ({
  conversationId: null,
  messages: [],
  streamingState: "idle",
  error: null,
  hasMoreMessages: false,
  loadingMore: false,
  selectedProjectIds: [],
  projectSelectionSource: "default",
  mailboxCount: 0,
  _abortController: null,

  setSelectedProjectIds: (ids) => set({ selectedProjectIds: ids, projectSelectionSource: "user" }),

  archiveConversation: async () => {
    const { conversationId } = get();
    if (!conversationId) return;
    try {
      await updateConversation(conversationId, { status: "archived" });
    } catch {
      // best effort
    }
  },

  loadConversation: async (id: string) => {
    // Abort any active stream before loading
    get()._abortController?.abort();

    set({
      conversationId: id,
      messages: [],
      streamingState: "idle",
      error: null,
      hasMoreMessages: false,
      loadingMore: false,
      selectedProjectIds: [],
      projectSelectionSource: "default",
      mailboxCount: 0,
      _abortController: null,
    });

    try {
      const [turnsData, detail] = await Promise.all([
        getConversationTurns(id, { includeDisplay: true, limit: TURNS_PAGE_SIZE }),
        getConversation(id),
      ]);
      const loadedMessages = turnsToMessages(turnsData.turns);
      set({
        messages: loadedMessages,
        hasMoreMessages: turnsData.has_more,
        selectedProjectIds: detail.latest_session?.project_ids ?? [],
        projectSelectionSource: "session",
        mailboxCount: detail.mailbox?.pending_count ?? 0,
      });

      // Reattach to active stream session if one exists
      if (detail.active_session?.transport === "stream") {
        const abortController = new AbortController();
        set({
          messages: [...loadedMessages, makeAssistantPlaceholder()],
          streamingState: "streaming",
          _abortController: abortController,
        });
        // Run bridge consumption in background (non-blocking for the load)
        consumeBridge(id, abortController.signal, get, set).catch(() => {
          // Errors are handled inside consumeBridge
        });
      }
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Failed to load conversation",
      });
    }
  },

  loadMoreMessages: async () => {
    const { conversationId, messages, hasMoreMessages, loadingMore } = get();
    if (!conversationId || !hasMoreMessages || loadingMore) return;

    // Find the oldest message with a sessionId (from turn history) as cursor.
    const firstHistoryMsg = messages.find((m) => m.sessionId);
    if (!firstHistoryMsg?.sessionId) return;

    set({ loadingMore: true });

    try {
      const { turns, has_more } = await getConversationTurns(conversationId, {
        includeDisplay: true,
        limit: TURNS_PAGE_SIZE,
        before: firstHistoryMsg.sessionId,
      });
      const olderMessages = turnsToMessages(turns);
      set((state) => ({
        messages: [...olderMessages, ...state.messages],
        hasMoreMessages: has_more,
        loadingMore: false,
      }));
    } catch {
      set({ loadingMore: false });
    }
  },

  sendMessage: async (text, opts, attachments) => {
    const { conversationId, streamingState, _abortController: existing } = get();

    // If already streaming, treat as steer
    if (streamingState === "streaming" && conversationId) {
      await get().steer(text);
      return;
    }

    // Abort any previous stream
    existing?.abort();

    const abortController = new AbortController();

    // Optimistically add user + assistant placeholder
    set((state) => ({
      messages: [...state.messages, makeUserMessage(text, attachments), makeAssistantPlaceholder()],
      streamingState: "connecting",
      error: null,
      _abortController: abortController,
    }));

    try {
      const { selectedProjectIds } = get();
      const body: ConversationRunRequest = {
        input: [...(text ? [{ type: "text" as const, text }] : []), ...(attachments ?? [])],
        transport: "stream", // Prefer stream transport for reconnection support
        project_ids: selectedProjectIds,
      };
      if (conversationId) {
        body.conversation_id = conversationId;
      } else {
        // New conversation: tag with workspace_id in metadata for sidebar filtering
        body.metadata = { workspace_id: opts.workspaceId };
      }
      if (opts.presetId) {
        body.preset_id = opts.presetId;
      }

      const response = await runConversation(body);
      const signal = abortController.signal;

      if (response.status === 202) {
        // Stream transport accepted -- connect to bridge endpoint
        const accepted = await response.json();
        set({ conversationId: accepted.conversation_id, streamingState: "streaming" });

        // Brief delay for background task startup
        await new Promise((r) => setTimeout(r, 100));

        await consumeBridge(accepted.conversation_id, signal, get, set);
        return;
      }

      if (response.status === 422) {
        // Redis not configured -- fall back to direct SSE transport
        body.transport = "sse";
        await consumeDirectSSE(body, signal, get, set);
        return;
      }

      if (response.status === 409) {
        // Conversation busy -- try to reattach to existing stream
        const busyBody = await response.json();
        const activeSession = busyBody.active_session;
        if (activeSession?.transport === "stream" && conversationId) {
          set({ streamingState: "streaming" });
          await consumeBridge(conversationId, signal, get, set);
          return;
        }
        throw new Error("Conversation already has an active session");
      }

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const errBody = await response.json();
          if (errBody?.detail) detail = String(errBody.detail);
        } catch {
          // ignore parse failure
        }
        throw new Error(detail);
      }

      // Unexpected success response (shouldn't happen for stream transport)
      for await (const event of parseSSEStream(response, signal)) {
        if (signal.aborted) break;
        handleEvent(event, get, set);
      }
    } catch (err) {
      if (abortController.signal.aborted) return; // intentional abort
      set((state) => ({
        streamingState: "error",
        error: err instanceof Error ? err.message : "Stream failed",
        _abortController: null,
        messages: updateLastAssistant(state.messages, (msg) => ({
          ...msg,
          isStreaming: false,
        })),
      }));
    }
  },

  interrupt: async () => {
    const { conversationId, _abortController } = get();
    if (!conversationId) return;

    try {
      await interruptConversation(conversationId);
    } catch {
      // Best effort -- the agent may have already finished
    }

    // Don't abort immediately -- let RUN_FINISHED/RUN_ERROR arrive naturally.
    // If the SSE stream is stuck, the user can navigate away (clearChat).
    // But as a safety net, abort after a short delay if still streaming.
    setTimeout(() => {
      if (get().streamingState === "streaming") {
        _abortController?.abort();
        set((state) => ({
          streamingState: "idle",
          _abortController: null,
          messages: updateLastAssistant(state.messages, (msg) => ({
            ...msg,
            isStreaming: false,
          })),
        }));
      }
    }, 3000);
  },

  steer: async (text) => {
    const { conversationId } = get();
    if (!conversationId) return;

    // Add user message to display
    set((state) => ({
      messages: [...state.messages, makeUserMessage(text)],
    }));

    try {
      await steerConversation(conversationId, {
        input: [{ type: "text", text }],
      });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Failed to send steering message",
      });
    }
  },

  clearChat: () => {
    get()._abortController?.abort();
    set({
      conversationId: null,
      messages: [],
      streamingState: "idle",
      error: null,
      hasMoreMessages: false,
      loadingMore: false,
      selectedProjectIds: [],
      projectSelectionSource: "default",
      mailboxCount: 0,
      _abortController: null,
    });
  },
}));
