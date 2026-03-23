import { useEffect, useCallback, useRef, useState } from "react";
import { useNavigate, useParams, NavLink } from "react-router-dom";
import {
  SquarePen,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sun,
  Moon,
  ChevronDown,
  Circle,
  LogOut,
  Pencil,
  FolderOpen,
  Search,
  Archive,
  MoreHorizontal,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { updateConversation, searchConversations } from "@/api/conversations";
import type { SearchConversationResult } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAppStore } from "@/stores/app";
import { useChatStore } from "@/stores/chat";
import { ensureDefaultWorkspace } from "@/api/workspaces";
import { listConversations } from "@/api/conversations";
import { listPresets } from "@/api/presets";
import type { ConversationResponse } from "@/api/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONVERSATIONS_PAGE_SIZE = 50;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days === 1) return "Yesterday";
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// ConversationItem
// ---------------------------------------------------------------------------

function ConversationItem({
  conv,
  active,
  isStreaming,
  onNavigate,
  onArchive,
}: {
  conv: ConversationResponse;
  active: boolean;
  isStreaming: boolean;
  onNavigate?: () => void;
  onArchive: (id: string) => void;
}) {
  const title = conv.title ?? "New conversation";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);
  const updateInList = useAppStore((s) => s.updateConversationInList);

  const commitRename = async () => {
    const trimmed = draft.trim();
    setEditing(false);
    if (!trimmed || trimmed === (conv.title ?? "New conversation")) return;
    try {
      const updated = await updateConversation(conv.conversation_id, { title: trimmed });
      updateInList(conv.conversation_id, { title: updated.title });
    } catch (err) {
      console.error("Failed to rename conversation:", err);
      toast.error("Failed to rename conversation");
      setDraft(conv.title ?? "New conversation");
    }
  };

  const startEditing = () => {
    setDraft(conv.title ?? "");
    setEditing(true);
    requestAnimationFrame(() => inputRef.current?.select());
  };

  if (editing) {
    return (
      <div className={["flex items-center rounded-xl px-3 py-1.5", "bg-sidebar-accent"].join(" ")}>
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void commitRename();
            if (e.key === "Escape") {
              setDraft(conv.title ?? "New conversation");
              setEditing(false);
            }
          }}
          onBlur={() => void commitRename()}
          className="flex-1 min-w-0 bg-transparent text-sm text-sidebar-accent-foreground outline-none placeholder:text-muted-foreground/50"
          placeholder="Conversation title"
          autoFocus
        />
      </div>
    );
  }

  return (
    <NavLink
      to={`/c/${conv.conversation_id}`}
      onClick={onNavigate}
      style={{ contentVisibility: "auto", containIntrinsicSize: "auto 36px" }}
      className={[
        "group flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-colors",
        "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
          : "text-muted-foreground",
      ].join(" ")}
    >
      {/* Active session indicator (pulsing dot) */}
      {isStreaming && (
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
        </span>
      )}
      <div className="flex-1 min-w-0">
        <span className="block truncate">{title}</span>
        {conv.summary && (
          <span className="block text-xs text-muted-foreground/60 truncate mt-0.5">
            {conv.summary}
          </span>
        )}
      </div>

      {/* Actions dropdown (visible on hover) */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            onClick={(e) => e.preventDefault()}
            className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-sidebar-border"
            title="Actions"
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-36">
          <DropdownMenuItem
            onClick={(e) => {
              e.preventDefault();
              startEditing();
            }}
          >
            <Pencil className="h-3.5 w-3.5 mr-2" />
            Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={(e) => {
              e.preventDefault();
              onArchive(conv.conversation_id);
            }}
            className="text-destructive focus:text-destructive"
          >
            <Archive className="h-3.5 w-3.5 mr-2" />
            Archive
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <span className="shrink-0 text-[11px] text-muted-foreground/50 group-hover:hidden">
        {formatRelativeTime(conv.updated_at)}
      </span>
    </NavLink>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

export default function Sidebar({ onNavigate }: { onNavigate?: () => void } = {}) {
  const { id: activeId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const {
    theme,
    toggleTheme,
    sidebarOpen,
    toggleSidebar,
    workspaces,
    setWorkspaces,
    currentWorkspaceId,
    setCurrentWorkspace,
    conversations,
    conversationsHasMore,
    setConversations,
    appendConversations,
    removeConversationFromList,
    setPresets,
    user,
    logout,
  } = useAppStore();

  // Streaming state from chat store (for active session indicator)
  const streamingConversationId = useChatStore((s) =>
    s.streamingState === "streaming" || s.streamingState === "connecting" ? s.conversationId : null,
  );

  // Active sessions from WS notifications (includes sessions from other clients)
  const activeSessions = useAppStore((s) => s.activeSessions);

  // Search / filter
  const [searchQuery, setSearchQuery] = useState("");
  const [searchVisible, setSearchVisible] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchConversationResult[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load more state
  const [loadingMore, setLoadingMore] = useState(false);

  const currentWorkspace = workspaces.find((w) => w.workspace_id === currentWorkspaceId);

  // Use ref for currentWorkspaceId to avoid re-triggering the load callback
  const currentWorkspaceIdRef = useRef(currentWorkspaceId);
  currentWorkspaceIdRef.current = currentWorkspaceId;

  const loadWorkspaces = useCallback(async () => {
    try {
      const [{ defaultWs, all }, presets] = await Promise.all([
        ensureDefaultWorkspace(),
        listPresets(),
      ]);
      setWorkspaces(all);
      setPresets(presets);
      // Auto-select default workspace if none selected or stale ID not in list
      const current = currentWorkspaceIdRef.current;
      if (!current || !all.some((w) => w.workspace_id === current)) {
        setCurrentWorkspace(defaultWs.workspace_id);
      }
    } catch (err) {
      console.error("Failed to load workspaces:", err);
    }
  }, [setWorkspaces, setPresets, setCurrentWorkspace]);

  const loadConversations = useCallback(async () => {
    if (!currentWorkspaceId) return;
    try {
      const convs = await listConversations({
        workspaceId: currentWorkspaceId,
        limit: CONVERSATIONS_PAGE_SIZE,
      });
      setConversations(convs, convs.length >= CONVERSATIONS_PAGE_SIZE);
    } catch (err) {
      console.error("Failed to load conversations:", err);
    }
  }, [currentWorkspaceId, setConversations]);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  // Reset search when workspace changes
  useEffect(() => {
    setSearchQuery("");
    setSearchResults(null);
  }, [currentWorkspaceId]);

  // Debounced server-side search
  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);

    const q = searchQuery.trim();
    if (!q) {
      setSearchResults(null);
      setSearchLoading(false);
      return;
    }

    // Short queries: client-side filter by title/summary (instant)
    if (q.length < 2) {
      setSearchResults(null);
      return;
    }

    // Longer queries: debounced server-side search
    setSearchLoading(true);
    searchTimerRef.current = setTimeout(() => {
      searchConversations({ q, limit: 30 })
        .then((res) => setSearchResults(res.conversations))
        .catch((err) => {
          console.error("Search failed:", err);
          setSearchResults(null);
        })
        .finally(() => setSearchLoading(false));
    }, 300);

    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    };
  }, [searchQuery]);

  const handleLoadMore = useCallback(async () => {
    if (!currentWorkspaceId || loadingMore) return;
    setLoadingMore(true);
    try {
      const convs = await listConversations({
        workspaceId: currentWorkspaceId,
        limit: CONVERSATIONS_PAGE_SIZE,
        offset: conversations.length,
      });
      appendConversations(convs, convs.length >= CONVERSATIONS_PAGE_SIZE);
    } catch (err) {
      console.error("Failed to load more conversations:", err);
    } finally {
      setLoadingMore(false);
    }
  }, [currentWorkspaceId, conversations.length, loadingMore, appendConversations]);

  const handleNewChat = () => {
    useChatStore.getState().clearChat();
    navigate("/");
    onNavigate?.();
  };

  const handleSwitchWorkspace = (id: string) => {
    setCurrentWorkspace(id);
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const handleArchiveConversation = useCallback(
    async (convId: string) => {
      try {
        await updateConversation(convId, { status: "archived" });
        removeConversationFromList(convId);
        // If the archived conversation is currently open, navigate away
        if (convId === activeId) {
          useChatStore.getState().clearChat();
          navigate("/");
        }
      } catch (err) {
        console.error("Failed to archive conversation:", err);
        toast.error("Failed to archive conversation");
      }
    },
    [activeId, navigate, removeConversationFromList],
  );

  // Filter conversations: server-side results or client-side fallback
  const filteredConversations = (() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return conversations;
    // If server-side results are available, use them
    if (searchResults !== null) return searchResults;
    // Short query fallback: client-side filter by title + summary
    return conversations.filter((c) => {
      const t = (c.title ?? "New conversation").toLowerCase();
      const s = (c.summary ?? "").toLowerCase();
      return t.includes(q) || s.includes(q);
    });
  })();

  // -----------------------------------------------------------------------
  // Collapsed sidebar -- slim icon bar
  // -----------------------------------------------------------------------

  if (!sidebarOpen) {
    return (
      <div className="flex h-full w-12 shrink-0 flex-col items-center border-r border-sidebar-border bg-sidebar py-3 gap-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleNewChat}
          className="text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
        >
          <SquarePen className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Expanded sidebar
  // -----------------------------------------------------------------------

  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-3 border-b border-sidebar-border">
        <span className="flex-1 font-semibold text-sm text-sidebar-foreground tracking-tight">
          Netherbrain
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => {
            setSearchVisible((v) => !v);
            if (searchVisible) setSearchQuery("");
          }}
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          title="Search conversations"
        >
          <Search className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleNewChat}
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          title="New chat"
        >
          <SquarePen className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          title="Collapse sidebar"
        >
          <PanelLeftClose className="h-4 w-4" />
        </Button>
      </div>

      {/* Workspace selector */}
      <div className="px-3 py-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              className="w-full justify-between text-sm h-8 rounded-xl border-sidebar-border"
            >
              <span className="truncate">{currentWorkspace?.name ?? "Select workspace"}</span>
              <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-56">
            {workspaces.map((ws) => (
              <DropdownMenuItem
                key={ws.workspace_id}
                onClick={() => handleSwitchWorkspace(ws.workspace_id)}
                className={ws.workspace_id === currentWorkspaceId ? "font-medium" : ""}
              >
                <Circle
                  className={[
                    "mr-2 h-2 w-2",
                    ws.workspace_id === currentWorkspaceId
                      ? "fill-primary text-primary"
                      : "opacity-0",
                  ].join(" ")}
                />
                {ws.name ?? ws.workspace_id}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => {
                navigate("/settings");
                onNavigate?.();
              }}
            >
              Manage workspaces
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Search input */}
      {searchVisible && (
        <div className="px-3 pb-2">
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations..."
            className="h-8 text-sm rounded-xl"
            autoFocus
          />
        </div>
      )}

      {/* Conversation list */}
      <ScrollArea className="flex-1 px-2">
        <div className="space-y-0.5 py-1">
          {filteredConversations.length === 0 ? (
            <p className="px-3 py-6 text-xs text-muted-foreground text-center leading-relaxed">
              {searchQuery.trim() ? (
                searchLoading ? (
                  "Searching..."
                ) : (
                  "No matching conversations."
                )
              ) : (
                <>
                  No conversations yet.
                  <br />
                  Start a new chat to begin.
                </>
              )}
            </p>
          ) : (
            <>
              {filteredConversations.map((conv) => (
                <ConversationItem
                  key={conv.conversation_id}
                  conv={conv}
                  active={conv.conversation_id === activeId}
                  isStreaming={
                    conv.conversation_id === streamingConversationId ||
                    activeSessions.has(conv.conversation_id)
                  }
                  onNavigate={onNavigate}
                  onArchive={handleArchiveConversation}
                />
              ))}
              {/* Load more button */}
              {conversationsHasMore && !searchQuery.trim() && (
                <div className="px-3 py-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full h-7 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => void handleLoadMore()}
                    disabled={loadingMore}
                  >
                    {loadingMore ? (
                      <>
                        <Loader2 className="h-3 w-3 mr-1.5 animate-spin" />
                        Loading...
                      </>
                    ) : (
                      "Load more"
                    )}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </ScrollArea>

      {/* Files section */}
      {currentWorkspace?.projects && currentWorkspace.projects.length > 0 && (
        <div className="px-2 py-2 border-t border-sidebar-border">
          <p className="px-3 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
            Files
          </p>
          {currentWorkspace.projects.map((proj) => (
            <NavLink
              key={proj.id}
              to={`/files/${proj.id}`}
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  "flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm transition-colors",
                  "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : "text-muted-foreground",
                ].join(" ")
              }
            >
              <FolderOpen className="h-4 w-4 shrink-0 text-amber-500" />
              <span className="truncate">{proj.id}</span>
            </NavLink>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center gap-1 px-3 py-3 border-t border-sidebar-border">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          onClick={toggleTheme}
          title="Toggle theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
        <span className="flex-1 text-xs text-muted-foreground truncate px-1">
          {user?.display_name ?? user?.user_id ?? ""}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          onClick={() => {
            navigate("/settings");
            onNavigate?.();
          }}
          title="Settings"
        >
          <Settings className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          onClick={handleLogout}
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
