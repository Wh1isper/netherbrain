/**
 * SSE stream parser for AG-UI protocol events.
 *
 * Reads a fetch Response body as Server-Sent Events and yields
 * parsed JSON objects matching the AG-UI event schema.
 */

// ---------------------------------------------------------------------------
// AG-UI event type constants (matches backend EventType enum values)
// ---------------------------------------------------------------------------

export const EventType = {
  // Lifecycle
  RUN_STARTED: "RUN_STARTED",
  RUN_FINISHED: "RUN_FINISHED",
  RUN_ERROR: "RUN_ERROR",
  // Text streaming
  TEXT_MESSAGE_START: "TEXT_MESSAGE_START",
  TEXT_MESSAGE_CONTENT: "TEXT_MESSAGE_CONTENT",
  TEXT_MESSAGE_END: "TEXT_MESSAGE_END",
  // Reasoning / thinking
  REASONING_START: "REASONING_START",
  REASONING_MESSAGE_START: "REASONING_MESSAGE_START",
  REASONING_MESSAGE_CONTENT: "REASONING_MESSAGE_CONTENT",
  REASONING_MESSAGE_END: "REASONING_MESSAGE_END",
  REASONING_END: "REASONING_END",
  // Tool calls
  TOOL_CALL_START: "TOOL_CALL_START",
  TOOL_CALL_ARGS: "TOOL_CALL_ARGS",
  TOOL_CALL_END: "TOOL_CALL_END",
  TOOL_CALL_RESULT: "TOOL_CALL_RESULT",
  // Extensions (delivered as CUSTOM)
  CUSTOM: "CUSTOM",
} as const;

export type EventTypeName = (typeof EventType)[keyof typeof EventType];

// ---------------------------------------------------------------------------
// AG-UI event interfaces (camelCase, matching JSON wire format)
// ---------------------------------------------------------------------------

export interface BaseAGUIEvent {
  type: string;
}

export interface RunStartedEvent extends BaseAGUIEvent {
  type: typeof EventType.RUN_STARTED;
  threadId: string;
  runId: string;
}

export interface RunFinishedEvent extends BaseAGUIEvent {
  type: typeof EventType.RUN_FINISHED;
  threadId?: string;
  runId?: string;
}

export interface RunErrorEvent extends BaseAGUIEvent {
  type: typeof EventType.RUN_ERROR;
  message: string;
  code?: string;
}

export interface TextMessageStartEvent extends BaseAGUIEvent {
  type: typeof EventType.TEXT_MESSAGE_START;
  messageId: string;
  role: string;
}

export interface TextMessageContentEvent extends BaseAGUIEvent {
  type: typeof EventType.TEXT_MESSAGE_CONTENT;
  messageId: string;
  delta: string;
}

export interface TextMessageEndEvent extends BaseAGUIEvent {
  type: typeof EventType.TEXT_MESSAGE_END;
  messageId: string;
}

export interface ReasoningStartEvent extends BaseAGUIEvent {
  type: typeof EventType.REASONING_START;
  messageId: string;
}

export interface ReasoningMessageContentEvent extends BaseAGUIEvent {
  type: typeof EventType.REASONING_MESSAGE_CONTENT;
  messageId: string;
  delta: string;
}

export interface ReasoningEndEvent extends BaseAGUIEvent {
  type: typeof EventType.REASONING_END;
  messageId: string;
}

export interface ToolCallStartEvent extends BaseAGUIEvent {
  type: typeof EventType.TOOL_CALL_START;
  toolCallId: string;
  toolCallName: string;
  parentMessageId: string;
}

export interface ToolCallArgsEvent extends BaseAGUIEvent {
  type: typeof EventType.TOOL_CALL_ARGS;
  toolCallId: string;
  delta: string;
}

export interface ToolCallEndEvent extends BaseAGUIEvent {
  type: typeof EventType.TOOL_CALL_END;
  toolCallId: string;
}

export interface ToolCallResultEvent extends BaseAGUIEvent {
  type: typeof EventType.TOOL_CALL_RESULT;
  messageId: string;
  toolCallId: string;
  content: string;
  role: string;
  status?: string;
}

export interface CustomEventData extends BaseAGUIEvent {
  type: typeof EventType.CUSTOM;
  name: string;
  value: Record<string, unknown>;
}

export type AGUIEvent =
  | RunStartedEvent
  | RunFinishedEvent
  | RunErrorEvent
  | TextMessageStartEvent
  | TextMessageContentEvent
  | TextMessageEndEvent
  | ReasoningStartEvent
  | ReasoningMessageContentEvent
  | ReasoningEndEvent
  | ToolCallStartEvent
  | ToolCallArgsEvent
  | ToolCallEndEvent
  | ToolCallResultEvent
  | CustomEventData
  | BaseAGUIEvent; // fallback for unknown event types

// ---------------------------------------------------------------------------
// SSE stream parser
// ---------------------------------------------------------------------------

/**
 * Parse an SSE stream from a fetch Response.
 *
 * Reads the response body incrementally and yields parsed AG-UI
 * event objects. Handles multi-line data fields and ignores
 * comment lines (`:` prefix) and event type fields.
 *
 * The optional `onEventId` callback is invoked with each SSE `id:` field,
 * enabling callers to track the last event ID for reconnection.
 */
export async function* parseSSEStream(
  response: Response,
  signal?: AbortSignal,
  onEventId?: (id: string) => void,
): AsyncGenerator<AGUIEvent> {
  const body = response.body;
  if (!body) throw new Error("Response body is not readable");

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) break;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE events are delimited by blank lines (\n\n)
      const parts = buffer.split("\n\n");
      // Last part may be incomplete -- keep it in buffer
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        const parsed = parseSSEBlock(part);
        if (parsed) {
          if (parsed.id && onEventId) onEventId(parsed.id);
          yield parsed.event;
        }
      }
    }

    // Flush remaining buffer
    if (buffer.trim()) {
      const parsed = parseSSEBlock(buffer);
      if (parsed) {
        if (parsed.id && onEventId) onEventId(parsed.id);
        yield parsed.event;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

interface ParsedSSEBlock {
  event: AGUIEvent;
  id: string | null;
}

/**
 * Parse a single SSE block (lines between blank-line delimiters)
 * into an AG-UI event object with its SSE event ID.
 */
function parseSSEBlock(raw: string): ParsedSSEBlock | null {
  const dataLines: string[] = [];
  let eventId: string | null = null;

  for (const line of raw.split("\n")) {
    // Skip comments and empty lines
    if (line.startsWith(":") || !line.trim()) continue;

    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    } else if (line.startsWith("id:")) {
      eventId = line.slice(3).trimStart();
    }
    // event: field is ignored (we parse type from JSON data)
  }

  if (dataLines.length === 0) return null;

  const data = dataLines.join("\n");

  try {
    return { event: JSON.parse(data) as AGUIEvent, id: eventId };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Terminal event detection
// ---------------------------------------------------------------------------

const TERMINAL_TYPES: ReadonlySet<string> = new Set([EventType.RUN_FINISHED, EventType.RUN_ERROR]);

export function isTerminalEvent(event: BaseAGUIEvent): boolean {
  return TERMINAL_TYPES.has(event.type);
}
