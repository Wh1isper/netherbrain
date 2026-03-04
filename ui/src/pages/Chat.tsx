import { useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useChatStore } from "@/stores/chat";
import { useAppStore } from "@/stores/app";
import { listConversations } from "@/api/conversations";
import MessageList from "@/components/chat/MessageList";
import ChatInput from "@/components/chat/ChatInput";
import ConversationHeader from "@/components/chat/ConversationHeader";

export default function Chat() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const conversationId = useChatStore((s) => s.conversationId);
  const messages = useChatStore((s) => s.messages);
  const streamingState = useChatStore((s) => s.streamingState);
  const error = useChatStore((s) => s.error);
  const loadConversation = useChatStore((s) => s.loadConversation);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const interrupt = useChatStore((s) => s.interrupt);
  const clearChat = useChatStore((s) => s.clearChat);

  const currentWorkspaceId = useAppStore((s) => s.currentWorkspaceId);
  const conversations = useAppStore((s) => s.conversations);
  const setConversations = useAppStore((s) => s.setConversations);

  // Find title from conversation list
  const convMeta = conversations.find((c) => c.conversation_id === (id ?? conversationId));
  const title = convMeta?.title ?? null;

  // Track URL id to detect changes
  const prevIdRef = useRef<string | undefined>(id);

  // -----------------------------------------------------------------------
  // Load conversation when URL changes
  // -----------------------------------------------------------------------

  useEffect(() => {
    if (id && id !== prevIdRef.current) {
      void loadConversation(id);
    } else if (!id && prevIdRef.current) {
      // Navigated to "/" from a conversation
      clearChat();
    }
    prevIdRef.current = id;
  }, [id, loadConversation, clearChat]);

  // -----------------------------------------------------------------------
  // Navigate to URL when new conversation is created via streaming
  // -----------------------------------------------------------------------

  const refreshConversations = useCallback(async () => {
    if (!currentWorkspaceId) return;
    try {
      const convs = await listConversations({
        workspaceId: currentWorkspaceId,
        limit: 50,
      });
      setConversations(convs);
    } catch {
      // Best effort
    }
  }, [currentWorkspaceId, setConversations]);

  useEffect(() => {
    // New conversation created during streaming -- navigate to its URL
    if (conversationId && !id) {
      navigate(`/c/${conversationId}`, { replace: true });
      prevIdRef.current = conversationId;
      void refreshConversations();
    }
  }, [conversationId, id, navigate, refreshConversations]);

  // Refresh conversation list when streaming finishes (updates timestamp/title)
  useEffect(() => {
    if (streamingState === "idle" && conversationId) {
      void refreshConversations();
    }
    // Only trigger when streamingState transitions to idle
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamingState]);

  // -----------------------------------------------------------------------
  // Handlers
  // -----------------------------------------------------------------------

  const handleSend = useCallback(
    (text: string) => {
      if (!currentWorkspaceId) return;
      void sendMessage(text, { workspaceId: currentWorkspaceId });
    },
    [currentWorkspaceId, sendMessage],
  );

  const handleInterrupt = useCallback(() => {
    void interrupt();
  }, [interrupt]);

  const handleTitleChange = useCallback(
    (newTitle: string) => {
      // Update the conversation in the sidebar list optimistically
      useAppStore.setState((state) => ({
        conversations: state.conversations.map((c) =>
          c.conversation_id === conversationId ? { ...c, title: newTitle } : c,
        ),
      }));
    },
    [conversationId],
  );

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div className="flex h-full flex-col">
      {(id || conversationId) && (
        <ConversationHeader
          conversationId={id ?? conversationId}
          title={title}
          presetName={convMeta?.default_preset_id}
          onTitleChange={handleTitleChange}
        />
      )}

      <MessageList messages={messages} />

      {error && (
        <div className="px-4 py-2 text-center text-sm text-destructive bg-destructive/5 border-t border-destructive/10">
          {error}
        </div>
      )}

      <ChatInput
        onSend={handleSend}
        onInterrupt={handleInterrupt}
        streamingState={streamingState}
        disabled={!currentWorkspaceId}
      />
    </div>
  );
}
