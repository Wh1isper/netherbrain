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
} from "lucide-react";
import { updateConversation } from "@/api/conversations";
import { Button } from "@/components/ui/button";
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

function ConversationItem({ conv, active }: { conv: ConversationResponse; active: boolean }) {
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
      setDraft(conv.title ?? "New conversation");
    }
  };

  const startEditing = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDraft(conv.title ?? "");
    setEditing(true);
    // Focus after render
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
      className={[
        "group flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-colors",
        "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
          : "text-muted-foreground",
      ].join(" ")}
    >
      <span className="flex-1 truncate">{title}</span>
      <button
        onClick={startEditing}
        className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-sidebar-border"
        title="Rename"
      >
        <Pencil className="h-3 w-3" />
      </button>
      <span className="shrink-0 text-[11px] text-muted-foreground/50 group-hover:hidden">
        {formatRelativeTime(conv.updated_at)}
      </span>
    </NavLink>
  );
}

export default function Sidebar() {
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
    setConversations,
    setPresets,
    user,
    logout,
  } = useAppStore();

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
        limit: 50,
      });
      setConversations(convs);
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

  const handleNewChat = () => {
    useChatStore.getState().clearChat();
    navigate("/");
  };

  const handleSwitchWorkspace = (id: string) => {
    setCurrentWorkspace(id);
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  // -----------------------------------------------------------------------
  // Collapsed sidebar — slim icon bar
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
            <DropdownMenuItem onClick={() => navigate("/settings")}>
              Manage workspaces
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Conversation list */}
      <ScrollArea className="flex-1 px-2">
        <div className="space-y-0.5 py-1">
          {conversations.length === 0 ? (
            <p className="px-3 py-6 text-xs text-muted-foreground text-center leading-relaxed">
              No conversations yet.
              <br />
              Start a new chat to begin.
            </p>
          ) : (
            conversations.map((conv) => (
              <ConversationItem
                key={conv.conversation_id}
                conv={conv}
                active={conv.conversation_id === activeId}
              />
            ))
          )}
        </div>
      </ScrollArea>

      {/* Files section */}
      {currentWorkspace?.projects && currentWorkspace.projects.length > 0 && (
        <div className="px-2 py-2 border-t border-sidebar-border">
          <p className="px-3 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
            Files
          </p>
          {currentWorkspace.projects.map((pid) => (
            <NavLink
              key={pid}
              to={`/files/${pid}`}
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
              <span className="truncate">{pid}</span>
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
          onClick={() => navigate("/settings")}
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
