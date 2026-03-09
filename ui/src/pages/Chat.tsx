import { useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Menu, Bot, Sparkles, MessageSquare } from "lucide-react";
import { toast } from "sonner";
import { useChatStore, getProjectCache, mergeUsage } from "@/stores/chat";
import { useAppStore } from "@/stores/app";
import { listConversations, prepareFork, updateConversation } from "@/api/conversations";
import { updateWorkspace, listWorkspaces } from "@/api/workspaces";
import type { InputPart } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useIsMobile, useGlobalShortcuts } from "@/lib/hooks";
import MessageList from "@/components/chat/MessageList";
import ChatInput from "@/components/chat/ChatInput";
import ConversationHeader from "@/components/chat/ConversationHeader";
import ProjectSelector from "@/components/chat/ProjectSelector";
import PresetSelector from "@/components/chat/PresetSelector";
import UsageIndicator from "@/components/chat/UsageIndicator";

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
  const usage = useChatStore((s) => s.usage);
  const conversationUsage = useChatStore((s) => s.conversationUsage);
  const archiveConversation = useChatStore((s) => s.archiveConversation);

  const selectedPresetId = useChatStore((s) => s.selectedPresetId);
  const setSelectedPresetId = useChatStore((s) => s.setSelectedPresetId);

  const currentWorkspaceId = useAppStore((s) => s.currentWorkspaceId);
  const workspaces = useAppStore((s) => s.workspaces);
  const setWorkspaces = useAppStore((s) => s.setWorkspaces);
  const presets = useAppStore((s) => s.presets);
  const conversations = useAppStore((s) => s.conversations);
  const setConversations = useAppStore((s) => s.setConversations);

  // Available projects from the current workspace
  const currentWorkspace = workspaces.find((w) => w.workspace_id === currentWorkspaceId);
  const availableProjects = useMemo(
    () => currentWorkspace?.projects ?? [],
    [currentWorkspace?.projects],
  );

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
      // Skip reload if we're already streaming this conversation
      // (happens when component remounts after new-conversation URL navigation)
      const state = useChatStore.getState();
      if (!(state.conversationId === id && state.streamingState !== "idle")) {
        void loadConversation(id);
      }
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
      setConversations(convs, convs.length >= 50);
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
  // Seed project selection from cache for new conversations
  // -----------------------------------------------------------------------

  useEffect(() => {
    // Only seed for new conversations (no existing conversation loaded)
    if (id || conversationId) return;
    if (!currentWorkspaceId) return;

    const cached = getProjectCache(currentWorkspaceId);
    // Filter to only include projects still available in the workspace
    const valid = cached.filter((p) => availableProjects.includes(p));
    if (valid.length > 0) {
      setSelectedProjectIds(valid);
    }
  }, [currentWorkspaceId, id, conversationId, availableProjects, setSelectedProjectIds]);

  // -----------------------------------------------------------------------
  // Handlers
  // -----------------------------------------------------------------------

  const handleSend = useCallback(
    (text: string, attachments?: InputPart[]) => {
      if (!currentWorkspaceId) return;
      void sendMessage(text, { workspaceId: currentWorkspaceId }, attachments);
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

  const handleFork = useCallback(async () => {
    const cid = id ?? conversationId;
    if (!cid || !currentWorkspaceId) return;
    try {
      const { conversation_id: newId } = await prepareFork(cid, {
        metadata: { workspace_id: currentWorkspaceId },
      });
      clearChat();
      navigate(`/c/${newId}`);
      void refreshConversations();
    } catch (err) {
      console.error("Failed to fork conversation:", err);
      toast.error("Failed to fork conversation");
    }
  }, [id, conversationId, currentWorkspaceId, clearChat, navigate, refreshConversations]);

  const handleArchive = useCallback(async () => {
    await archiveConversation();
    clearChat();
    navigate("/");
    void refreshConversations();
  }, [archiveConversation, clearChat, navigate, refreshConversations]);

  const handleChangePreset = useCallback(
    async (presetId: string) => {
      const cid = id ?? conversationId;
      if (!cid) return;
      try {
        await updateConversation(cid, { default_preset_id: presetId });
        setSelectedPresetId(presetId);
        // Update conversation in sidebar list
        useAppStore.setState((state) => ({
          conversations: state.conversations.map((c) =>
            c.conversation_id === cid ? { ...c, default_preset_id: presetId } : c,
          ),
        }));
      } catch (err) {
        console.error("Failed to change preset:", err);
        toast.error("Failed to change preset");
      }
    },
    [id, conversationId, setSelectedPresetId],
  );

  // -----------------------------------------------------------------------
  // Mobile helpers
  // -----------------------------------------------------------------------

  const isMobile = useIsMobile();
  const setMobileSidebarOpen = useAppStore((s) => s.setMobileSidebarOpen);
  const hasConversation = !!(id || conversationId);

  // -----------------------------------------------------------------------
  // Keyboard shortcuts
  // -----------------------------------------------------------------------

  useGlobalShortcuts({
    onNewChat: useCallback(() => {
      clearChat();
      navigate("/");
    }, [clearChat, navigate]),
    onFocusInput: useCallback(() => {
      const textarea = document.querySelector<HTMLTextAreaElement>("textarea[placeholder]");
      textarea?.focus();
    }, []),
  });

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div className="flex h-full flex-col">
      {/* Mobile header: hamburger (new chat) or conversation header with back */}
      {isMobile && !hasConversation && (
        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setMobileSidebarOpen(true)}
          >
            <Menu className="h-4 w-4" />
          </Button>
          <span className="text-sm font-semibold text-foreground">Netherbrain</span>
        </div>
      )}

      {hasConversation && (
        <ConversationHeader
          conversationId={id ?? conversationId}
          title={title}
          presetName={convMeta?.default_preset_id}
          projectIds={selectedProjectIds}
          mailboxCount={mailboxCount}
          onTitleChange={handleTitleChange}
          onFork={handleFork}
          onArchive={handleArchive}
          onFired={handleFired}
          onChangePreset={handleChangePreset}
          isMobile={isMobile}
          onOpenSidebar={() => setMobileSidebarOpen(true)}
        />
      )}

      {hasConversation ? (
        <MessageList
          messages={messages}
          hasMoreMessages={hasMoreMessages}
          loadingMore={loadingMore}
          onLoadMore={loadMoreMessages}
        />
      ) : (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="max-w-md text-center space-y-6">
            <div className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 mx-auto">
              <Bot className="h-7 w-7 text-primary" />
            </div>
            <div className="space-y-2">
              <h2 className="text-xl font-semibold text-foreground">Welcome to Netherbrain</h2>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Start a conversation below. Your messages will be processed by the selected preset's
                model.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-3 justify-center text-xs text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <MessageSquare className="h-3.5 w-3.5" />
                <span>Chat with AI agents</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5" />
                <span>Tool use and code execution</span>
              </div>
            </div>
          </div>
        </div>
      )}

      <UsageIndicator
        usage={mergeUsage(conversationUsage, usage)}
        streaming={streamingState === "streaming" || streamingState === "connecting"}
      />

      {error && (
        <div className="px-4 py-2 text-center text-sm text-destructive bg-destructive/5 border-t border-destructive/10">
          {error}
        </div>
      )}

      {currentWorkspaceId && (
        <div className="flex items-center gap-3 px-4 py-1.5 border-t border-border/50">
          <PresetSelector
            presets={presets}
            selected={selectedPresetId}
            onChange={setSelectedPresetId}
            disabled={streamingState === "streaming" || streamingState === "connecting"}
          />
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
