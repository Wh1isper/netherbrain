import { useState, useRef, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Check, Pencil, X } from "lucide-react";
import { updateConversation } from "@/api/conversations";

interface ConversationHeaderProps {
  conversationId: string | null;
  title: string | null;
  presetName?: string | null;
  onTitleChange?: (title: string) => void;
}

export default function ConversationHeader({
  conversationId,
  title,
  presetName,
  onTitleChange,
}: ConversationHeaderProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
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
    <div className="flex items-center gap-3 border-b border-border px-4 py-2.5 min-h-[49px]">
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
              onClick={() => void saveTitle()}
              className="text-muted-foreground hover:text-foreground"
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <button onClick={cancelEditing} className="text-muted-foreground hover:text-foreground">
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
      {presetName && (
        <Badge variant="secondary" className="shrink-0 text-xs">
          {presetName}
        </Badge>
      )}
    </div>
  );
}
