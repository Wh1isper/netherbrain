/**
 * WebSocket notification client with automatic reconnection.
 *
 * Connects to `WS /api/notifications?token=...` and dispatches typed
 * notification events. Handles ping/pong keepalive and exponential
 * backoff reconnection.
 */

import { getAuthToken } from "@/api/client";

// ---------------------------------------------------------------------------
// Notification event types (mirrors backend notifications/__init__.py)
// ---------------------------------------------------------------------------

export interface SessionStartedNotification {
  type: "session_started";
  conversation_id: string;
  session_id: string;
  session_type: string;
  transport: string;
  timestamp: string;
}

export interface SessionCompletedNotification {
  type: "session_completed";
  conversation_id: string;
  session_id: string;
  session_type: string;
  final_message_preview: string | null;
  timestamp: string;
}

export interface SessionFailedNotification {
  type: "session_failed";
  conversation_id: string;
  session_id: string;
  session_type: string;
  error: string | null;
  timestamp: string;
}

export interface MailboxUpdatedNotification {
  type: "mailbox_updated";
  conversation_id: string;
  message_id: string;
  source_session_id: string;
  source_type: string;
  subagent_name: string;
  pending_count: number;
  timestamp: string;
}

export interface ConversationUpdatedNotification {
  type: "conversation_updated";
  conversation_id: string;
  changes: string[];
  timestamp: string;
}

export type NotificationEvent =
  | SessionStartedNotification
  | SessionCompletedNotification
  | SessionFailedNotification
  | MailboxUpdatedNotification
  | ConversationUpdatedNotification;

export type NotificationHandler = (event: NotificationEvent) => void;

// ---------------------------------------------------------------------------
// Connection manager
// ---------------------------------------------------------------------------

export interface NotificationClientOptions {
  /** Callback for every notification event. */
  onEvent: NotificationHandler;
  /** Called when connection state changes. */
  onStatusChange?: (connected: boolean) => void;
  /** Ping interval in ms (default: 30000). */
  pingInterval?: number;
  /** Maximum reconnect delay in ms (default: 30000). */
  maxReconnectDelay?: number;
}

const DEFAULT_PING_INTERVAL = 30_000;
const DEFAULT_MAX_RECONNECT_DELAY = 30_000;
const BASE_RECONNECT_DELAY = 1_000;

/**
 * Create a managed WebSocket connection to the notification endpoint.
 *
 * Returns a `disconnect` function to tear down the connection.
 */
export function connectNotifications(opts: NotificationClientOptions): () => void {
  const {
    onEvent,
    onStatusChange,
    pingInterval = DEFAULT_PING_INTERVAL,
    maxReconnectDelay = DEFAULT_MAX_RECONNECT_DELAY,
  } = opts;

  let ws: WebSocket | null = null;
  let pingTimer: ReturnType<typeof setInterval> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempt = 0;
  let intentionalClose = false;

  function buildUrl(): string {
    const token = getAuthToken();
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    return `${proto}//${host}/api/notifications?token=${token ?? ""}`;
  }

  function startPing() {
    stopPing();
    pingTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, pingInterval);
  }

  function stopPing() {
    if (pingTimer !== null) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  function scheduleReconnect() {
    if (intentionalClose) return;
    const delay = Math.min(BASE_RECONNECT_DELAY * 2 ** reconnectAttempt, maxReconnectDelay);
    reconnectAttempt++;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function connect() {
    if (intentionalClose) return;

    // Don't connect without auth
    const token = getAuthToken();
    if (!token) {
      scheduleReconnect();
      return;
    }

    try {
      ws = new WebSocket(buildUrl());
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      reconnectAttempt = 0;
      onStatusChange?.(true);
      startPing();
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as { type: string };
        // Skip pong and error frames -- only forward notification events
        if (data.type === "pong" || data.type === "error") return;
        onEvent(data as NotificationEvent);
      } catch {
        // Ignore malformed frames
      }
    };

    ws.onclose = () => {
      stopPing();
      onStatusChange?.(false);
      ws = null;
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose will fire after onerror -- reconnect handled there
    };
  }

  function disconnect() {
    intentionalClose = true;
    stopPing();
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      ws.onclose = null; // Prevent reconnect on intentional close
      ws.close();
      ws = null;
    }
    onStatusChange?.(false);
  }

  // Start initial connection
  connect();

  return disconnect;
}
