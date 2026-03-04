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
  getConversationTurns,
  interruptConversation,
  steerConversation,
} from "../api/conversations";
import type { ConversationRunRequest, TurnResponse } from "../api/types";

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
}

export type StreamingState = "idle" | "connecting" | "streaming" | "error";

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

interface ChatState {
  conversationId: string | null;
  messages: ChatMessage[];
  streamingState: StreamingState;
  error: string | null;

  /** Load an existing conversation's turn history. */
  loadConversation: (id: string) => Promise<void>;

  /** Send a message (new conversation or continue existing). */
  sendMessage: (text: string, opts: { workspaceId: string; presetId?: string }) => Promise<void>;

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

/** Convert turn history into ChatMessage array. */
function turnsToMessages(turns: TurnResponse[]): ChatMessage[] {
  const messages: ChatMessage[] = [];

  for (const turn of turns) {
    // User message from input parts
    if (turn.input?.length) {
      const textParts = turn.input.filter((p) => p.type === "text" && p.text).map((p) => p.text!);
      if (textParts.length > 0) {
        messages.push({
          id: `${turn.session_id}-user`,
          role: "user",
          content: textParts.join("\n"),
          thinking: "",
          toolCalls: [],
          isStreaming: false,
        });
      }
    }

    // Assistant response from final_message
    if (turn.final_message !== null && turn.final_message !== undefined) {
      messages.push({
        id: `${turn.session_id}-assistant`,
        role: "assistant",
        content: turn.final_message,
        thinking: "",
        toolCalls: [],
        isStreaming: false,
      });
    }
  }

  return messages;
}

/** Create a blank user ChatMessage. */
function makeUserMessage(text: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role: "user",
    content: text,
    thinking: "",
    toolCalls: [],
    isStreaming: false,
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
  };
}

// ---------------------------------------------------------------------------
// SSE event handler
// ---------------------------------------------------------------------------

function handleEvent(
  event: AGUIEvent,
  get: () => ChatState,
  set: (updater: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
): void {
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
// Store
// ---------------------------------------------------------------------------

export const useChatStore = create<ChatState>()((set, get) => ({
  conversationId: null,
  messages: [],
  streamingState: "idle",
  error: null,
  _abortController: null,

  loadConversation: async (id: string) => {
    // Abort any active stream before loading
    get()._abortController?.abort();

    set({
      conversationId: id,
      messages: [],
      streamingState: "idle",
      error: null,
      _abortController: null,
    });

    try {
      const turns = await getConversationTurns(id);
      set({ messages: turnsToMessages(turns) });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Failed to load conversation",
      });
    }
  },

  sendMessage: async (text, opts) => {
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
      messages: [...state.messages, makeUserMessage(text), makeAssistantPlaceholder()],
      streamingState: "connecting",
      error: null,
      _abortController: abortController,
    }));

    try {
      const body: ConversationRunRequest = {
        input: [{ type: "text", text }],
        transport: "sse",
        workspace_id: opts.workspaceId,
      };
      if (conversationId) {
        body.conversation_id = conversationId;
      } else {
        // New conversation: tag with workspace_id in metadata
        body.metadata = { workspace_id: opts.workspaceId };
      }
      if (opts.presetId) {
        body.preset_id = opts.presetId;
      }

      const response = await runConversation(body);

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body?.detail) detail = String(body.detail);
        } catch {
          // ignore parse failure
        }
        throw new Error(detail);
      }

      // Process SSE events (runs until stream ends or abort)
      const signal = abortController.signal;
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
      _abortController: null,
    });
  },
}));
