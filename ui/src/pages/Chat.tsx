import { useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useChatStore } from "@/stores/chat";
import { useAppStore } from "@/stores/app";
import { listConversations } from "@/api/conversations";
import { updateWorkspace, listWorkspaces } from "@/api/workspaces";
import MessageList from "@/components/chat/MessageList";
import ChatInput from "@/components/chat/ChatInput";
import ConversationHeader from "@/components/chat/ConversationHeader";
import ProjectSelector from "@/components/chat/ProjectSelector";

export default function Chat() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const conversationId = useChatStore((s) => s.conversationId);
  const messages = useChatStore((s) => s.messages);
  const streamingState = useChatStore((s) => s.streamingState);
  const error = useChatStore((s) => s.error);
  const hasMoreMessages = useChatStore((s) => s.hasMoreMessages);
  const loadingMore = useChatStore((s) => s.loadingMore);
  const selectedProjectIds = useChatStore((s) => s.selectedProjectIds);
  const setSelectedProjectIds = useChatStore((s) => s.setSelectedProjectIds);
  const loadConversation = useChatStore((s) => s.loadConversation);
  const loadMoreMessages = useChatStore((s) => s.loadMoreMessages);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const interrupt = useChatStore((s) => s.interrupt);
  const clearChat = useChatStore((s) => s.clearChat);
  const mailboxCount = useChatStore((s) => s.mailboxCount);
  const archiveConversation = useChatStore((s) => s.archiveConversation);

  const currentWorkspaceId = useAppStore((s) => s.currentWorkspaceId);
  const workspaces = useAppStore((s) => s.workspaces);
  const setWorkspaces = useAppStore((s) => s.setWorkspaces);
  const conversations = useAppStore((s) => s.conversations);
  const setConversations = useAppStore((s) => s.setConversations);

  // Available projects from the current workspace
  const currentWorkspace = workspaces.find((w) => w.workspace_id === currentWorkspaceId);
  const availableProjects = currentWorkspace?.projects ?? [];

  // Find title from conversation list
  const convMeta = conversations.find((c) => c.conversation_id === (id ?? conversationId));
  const title = convMeta?.title ?? null;

  // Track URL id to detect changes
  const prevIdRef = useRef<string | undefined>(undefined);

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

  const handleCreateProject = useCallback(
    async (name: string) => {
      if (!currentWorkspaceId || !currentWorkspace) return;
      const updatedProjects = [...currentWorkspace.projects, name];
      await updateWorkspace(currentWorkspaceId, { projects: updatedProjects });
      // Refresh workspace list to pick up the new project
      const all = await listWorkspaces();
      setWorkspaces(all);
      // Auto-select the newly created project
      setSelectedProjectIds([...selectedProjectIds, name]);
    },
    [
      currentWorkspaceId,
      currentWorkspace,
      setWorkspaces,
      selectedProjectIds,
      setSelectedProjectIds,
    ],
  );

  const handleFired = useCallback(() => {
    const cid = id ?? conversationId;
    if (cid) void loadConversation(cid);
    void refreshConversations();
  }, [id, conversationId, loadConversation, refreshConversations]);

  const handleArchive = useCallback(async () => {
    await archiveConversation();
    clearChat();
    navigate("/");
    void refreshConversations();
  }, [archiveConversation, clearChat, navigate, refreshConversations]);

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
          projectIds={selectedProjectIds}
          mailboxCount={mailboxCount}
          onTitleChange={handleTitleChange}
          onArchive={handleArchive}
          onFired={handleFired}
        />
      )}

      <MessageList
        messages={messages}
        hasMoreMessages={hasMoreMessages}
        loadingMore={loadingMore}
        onLoadMore={loadMoreMessages}
      />

      {error && (
        <div className="px-4 py-2 text-center text-sm text-destructive bg-destructive/5 border-t border-destructive/10">
          {error}
        </div>
      )}

      {currentWorkspaceId && (
        <ProjectSelector
          projects={availableProjects}
          selected={selectedProjectIds}
          onChange={setSelectedProjectIds}
          onCreateProject={handleCreateProject}
          disabled={streamingState === "streaming" || streamingState === "connecting"}
        />
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
