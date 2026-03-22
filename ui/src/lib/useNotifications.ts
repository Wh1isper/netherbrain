/**
 * React hook that connects the WebSocket notification channel to Zustand stores.
 *
 * Mounted once in AppShell. Dispatches notification events to update:
 * - Sidebar conversation list (title, timestamp, active session indicator)
 * - Chat mailbox count (for badge + auto-fire)
 * - Active session tracking (pulsing dot on sidebar items)
 */

import { useEffect, useRef } from "react";
import { connectNotifications, type NotificationEvent } from "@/lib/notifications";
import { useAppStore } from "@/stores/app";
import { useChatStore } from "@/stores/chat";
import { getConversation } from "@/api/conversations";

/**
 * Debounce helper: collapses rapid calls for the same key into one execution
 * after `delay` ms of quiet. Used to batch rapid session_completed events
 * into a single API call per conversation.
 */
function createDebouncedMap(delay: number) {
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  return {
    schedule(key: string, fn: () => void) {
      const existing = timers.get(key);
      if (existing) clearTimeout(existing);
      timers.set(
        key,
        setTimeout(() => {
          timers.delete(key);
          fn();
        }, delay),
      );
    },
    clear() {
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
    },
  };
}

/**
 * Refresh a single conversation in the sidebar list.
 * Fetches fresh data and patches the list entry in-place.
 * If the conversation is not in the current list, it is prepended (new conversation
 * from another client, e.g. IM gateway).
 */
async function refreshConversationInList(conversationId: string) {
  try {
    const detail = await getConversation(conversationId);
    const { conversations, currentWorkspaceId } = useAppStore.getState();

    // Check if this conversation belongs to the current workspace
    const wsId = (detail.metadata as Record<string, unknown> | null)?.workspace_id as
      | string
      | undefined;
    if (wsId && currentWorkspaceId && wsId !== currentWorkspaceId) return;

    const exists = conversations.some((c) => c.conversation_id === conversationId);
    if (exists) {
      // If archived, remove from list instead of updating
      if (detail.status === "archived") {
        useAppStore.getState().removeConversationFromList(conversationId);
        return;
      }
      useAppStore.getState().updateConversationInList(conversationId, {
        title: detail.title,
        status: detail.status,
        updated_at: detail.updated_at,
        default_preset_id: detail.default_preset_id,
      });
    } else if (wsId === currentWorkspaceId) {
      // New conversation (e.g. from IM gateway) -- prepend to list
      useAppStore.setState((state) => ({
        conversations: [
          {
            conversation_id: detail.conversation_id,
            title: detail.title,
            default_preset_id: detail.default_preset_id,
            metadata: detail.metadata,
            status: detail.status,
            created_at: detail.created_at,
            updated_at: detail.updated_at,
          },
          ...state.conversations,
        ],
      }));
    }
  } catch {
    // Best effort -- conversation may have been deleted
  }
}

export function useNotifications() {
  const disconnectRef = useRef<(() => void) | null>(null);
  const debouncerRef = useRef(createDebouncedMap(500));

  useEffect(() => {
    const debouncer = debouncerRef.current;

    function handleEvent(event: NotificationEvent) {
      switch (event.type) {
        case "session_started": {
          useAppStore.getState().addActiveSession(event.conversation_id);
          break;
        }

        case "session_completed":
        case "session_failed": {
          useAppStore.getState().removeActiveSession(event.conversation_id);

          // Debounced refresh of the conversation in sidebar
          debouncer.schedule(event.conversation_id, () => {
            void refreshConversationInList(event.conversation_id);
          });
          break;
        }

        case "mailbox_updated": {
          // Update mailbox badge if this is the currently viewed conversation.
          // Auto-fire is handled by Chat.tsx reacting to mailboxCount changes.
          const chatState = useChatStore.getState();
          if (chatState.conversationId === event.conversation_id) {
            useChatStore.setState({ mailboxCount: event.pending_count });
          }
          break;
        }

        case "conversation_updated": {
          // Refresh the conversation in the sidebar list
          debouncer.schedule(event.conversation_id, () => {
            void refreshConversationInList(event.conversation_id);
          });
          break;
        }
      }
    }

    disconnectRef.current = connectNotifications({
      onEvent: handleEvent,
    });

    return () => {
      disconnectRef.current?.();
      disconnectRef.current = null;
      debouncer.clear();
    };
  }, []);

  // No return value -- this hook is purely side-effectful
}
