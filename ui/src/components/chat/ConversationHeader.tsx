import { useState, useRef, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Archive,
  Check,
  FolderOpen,
  GitFork,
  Inbox,
  MoreHorizontal,
  Pencil,
  X,
  Zap,
} from "lucide-react";
import { updateConversation, getMailbox, fireConversation } from "@/api/conversations";
import type { MailboxMessageResponse } from "@/api/types";

interface ConversationHeaderProps {
  conversationId: string | null;
  title: string | null;
  presetName?: string | null;
  projectIds?: string[];
  mailboxCount?: number;
  onTitleChange?: (title: string) => void;
  onArchive?: () => void;
  onFired?: () => void;
}

function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

function MailboxDialog({
  open,
  onOpenChange,
  conversationId,
  onFired,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conversationId: string;
  onFired?: () => void;
}) {
  const [messages, setMessages] = useState<MailboxMessageResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [firing, setFiring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    getMailbox(conversationId, { pendingOnly: true, limit: 50 })
      .then(setMessages)
      .catch(() => setError("Failed to load mailbox."))
      .finally(() => setLoading(false));
  }, [open, conversationId]);

  const handleFire = async () => {
    setFiring(true);
    setError(null);
    try {
      const response = await fireConversation(conversationId, { transport: "stream" });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `HTTP ${response.status}`);
      }
      onOpenChange(false);
      onFired?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fire continuation.");
    } finally {
      setFiring(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Mailbox</DialogTitle>
          <DialogDescription>
            Pending messages from async subagents. Fire to process them.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-60 overflow-y-auto space-y-2">
          {loading ? (
            <p className="text-sm text-muted-foreground py-4 text-center">Loading...</p>
          ) : messages.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No pending messages.</p>
          ) : (
            messages.map((m) => (
              <div key={m.message_id} className="rounded-md border border-border px-3 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                    {m.source_type}
                  </Badge>
                  <span className="font-medium">{m.subagent_name}</span>
                  <span className="text-xs text-muted-foreground ml-auto">
                    {new Date(m.created_at).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            onClick={() => void handleFire()}
            disabled={firing || messages.length === 0}
            className="gap-1.5"
          >
            <Zap className="h-3.5 w-3.5" />
            {firing ? "Firing..." : "Fire"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function ConversationHeader({
  conversationId,
  title,
  presetName,
  projectIds,
  mailboxCount = 0,
  onTitleChange,
  onArchive,
  onFired,
}: ConversationHeaderProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [mailboxOpen, setMailboxOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const displayTitle = title || "New Conversation";

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const startEditing = useCallback(() => {
    if (!conversationId) return;
    setEditValue(title || "");
    setEditing(true);
  }, [conversationId, title]);

  const saveTitle = useCallback(async () => {
    const newTitle = editValue.trim();
    setEditing(false);
    if (!conversationId || !newTitle || newTitle === title) return;

    try {
      await updateConversation(conversationId, { title: newTitle });
      onTitleChange?.(newTitle);
    } catch {
      // Revert on error -- the old title stays
    }
  }, [conversationId, editValue, title, onTitleChange]);

  const cancelEditing = useCallback(() => {
    setEditing(false);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") void saveTitle();
      if (e.key === "Escape") cancelEditing();
    },
    [saveTitle, cancelEditing],
  );

  return (
    <div className="flex items-center gap-3 border-b border-border/60 px-4 py-2.5 min-h-[49px] bg-background/80 backdrop-blur-sm">
      <div className="flex items-center gap-2 flex-1 min-w-0">
        {editing ? (
          <div className="flex items-center gap-1.5 flex-1">
            <Input
              ref={inputRef}
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onBlur={() => void saveTitle()}
              className="h-7 text-sm"
            />
            <button
              onMouseDown={(e) => {
                e.preventDefault();
                void saveTitle();
              }}
              className="text-muted-foreground hover:text-primary transition-colors"
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <button
              onMouseDown={(e) => {
                e.preventDefault();
                cancelEditing();
              }}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <button
            onClick={startEditing}
            className="flex items-center gap-1.5 group min-w-0"
            title="Click to edit title"
          >
            <span className="text-sm font-medium truncate">{displayTitle}</span>
            {conversationId && (
              <Pencil className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
            )}
          </button>
        )}
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {projectIds && projectIds.length > 0 && (
          <TooltipProvider delayDuration={300}>
            <div className="flex items-center gap-1">
              <FolderOpen className="h-3 w-3 text-muted-foreground" />
              {projectIds.map((p, i) => (
                <Tooltip key={p}>
                  <TooltipTrigger asChild>
                    <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-normal">
                      {i === 0 && <span className="mr-0.5 text-[9px] opacity-60">cwd</span>}
                      {basename(p)}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    <p>{p}</p>
                  </TooltipContent>
                </Tooltip>
              ))}
            </div>
          </TooltipProvider>
        )}
        {presetName && (
          <Badge variant="secondary" className="shrink-0 text-xs rounded-lg">
            {presetName}
          </Badge>
        )}

        {/* Mailbox indicator */}
        {mailboxCount > 0 && (
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 gap-1 text-xs"
                  onClick={() => setMailboxOpen(true)}
                >
                  <Inbox className="h-3.5 w-3.5" />
                  <span>{mailboxCount}</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>
                  {mailboxCount} pending mailbox message{mailboxCount !== 1 ? "s" : ""}
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        {/* Actions menu */}
        {conversationId && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {mailboxCount > 0 && (
                <>
                  <DropdownMenuItem onClick={() => setMailboxOpen(true)}>
                    <Inbox className="h-3.5 w-3.5 mr-2" />
                    View mailbox ({mailboxCount})
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              <DropdownMenuItem disabled>
                <GitFork className="h-3.5 w-3.5 mr-2" />
                Fork conversation
              </DropdownMenuItem>
              {onArchive && (
                <DropdownMenuItem
                  onClick={onArchive}
                  className="text-destructive focus:text-destructive"
                >
                  <Archive className="h-3.5 w-3.5 mr-2" />
                  Archive
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {/* Mailbox dialog */}
      {conversationId && (
        <MailboxDialog
          open={mailboxOpen}
          onOpenChange={setMailboxOpen}
          conversationId={conversationId}
          onFired={onFired}
        />
      )}
    </div>
  );
}
