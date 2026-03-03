import { useEffect, useCallback } from "react";
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
} from "lucide-react";
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
import { listWorkspaces, ensureDefaultWorkspace } from "@/api/workspaces";
import { listConversations } from "@/api/conversations";
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

  return (
    <NavLink
      to={`/c/${conv.conversation_id}`}
      className={[
        "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
        "hover:bg-accent hover:text-accent-foreground",
        active ? "bg-accent text-accent-foreground font-medium" : "text-muted-foreground",
      ].join(" ")}
    >
      <span className="flex-1 truncate">{title}</span>
      <span className="shrink-0 text-xs text-muted-foreground/60">
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
  } = useAppStore();

  const currentWorkspace = workspaces.find((w) => w.workspace_id === currentWorkspaceId);

  const loadWorkspaces = useCallback(async () => {
    try {
      const defaultWs = await ensureDefaultWorkspace();
      const all = await listWorkspaces();
      setWorkspaces(all);
      if (!currentWorkspaceId) {
        setCurrentWorkspace(defaultWs.workspace_id);
      }
    } catch (err) {
      console.error("Failed to load workspaces:", err);
    }
  }, [currentWorkspaceId, setWorkspaces, setCurrentWorkspace]);

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
    navigate("/");
  };

  const handleSwitchWorkspace = (id: string) => {
    setCurrentWorkspace(id);
  };

  if (!sidebarOpen) {
    return (
      <div className="flex h-full w-12 shrink-0 flex-col items-center border-r border-border bg-sidebar py-3 gap-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="text-muted-foreground"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleNewChat}
          className="text-muted-foreground"
        >
          <SquarePen className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-sidebar">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-3 border-b border-border">
        <span className="flex-1 font-semibold text-sm text-sidebar-foreground">Netherbrain</span>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleNewChat}
          className="h-7 w-7 text-muted-foreground hover:text-foreground"
          title="New chat"
        >
          <SquarePen className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="h-7 w-7 text-muted-foreground hover:text-foreground"
          title="Collapse sidebar"
        >
          <PanelLeftClose className="h-4 w-4" />
        </Button>
      </div>

      {/* Workspace selector */}
      <div className="px-3 py-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="w-full justify-between text-sm h-8">
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
            <p className="px-3 py-4 text-xs text-muted-foreground text-center">
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

      {/* Footer */}
      <div className="flex items-center gap-1 px-3 py-3 border-t border-border">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground"
          onClick={toggleTheme}
          title="Toggle theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground"
          onClick={() => navigate("/settings")}
          title="Settings"
        >
          <Settings className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
