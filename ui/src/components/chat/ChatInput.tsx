import { useRef, useEffect, useCallback } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { StreamingState } from "@/stores/chat";

interface ChatInputProps {
  onSend: (text: string) => void;
  onInterrupt: () => void;
  streamingState: StreamingState;
  disabled?: boolean;
}

export default function ChatInput({
  onSend,
  onInterrupt,
  streamingState,
  disabled,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isStreaming = streamingState === "streaming" || streamingState === "connecting";

  // Auto-resize textarea to content
  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  // Focus textarea on mount and when streaming ends
  useEffect(() => {
    if (!isStreaming) {
      textareaRef.current?.focus();
    }
  }, [isStreaming]);

  const handleSend = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    const text = el.value.trim();
    if (!text) return;
    onSend(text);
    el.value = "";
    el.style.height = "auto";
  }, [onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (isStreaming) {
          // During streaming, Enter sends as steer
          const text = textareaRef.current?.value.trim();
          if (text) handleSend();
        } else {
          handleSend();
        }
      }
    },
    [handleSend, isStreaming],
  );

  return (
    <div className="bg-background px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-border bg-card px-3 py-2 shadow-sm transition-shadow focus-within:shadow-md focus-within:border-primary/20">
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder={isStreaming ? "Send a message to guide the agent..." : "Send a message..."}
            className="flex-1 resize-none bg-transparent px-1 py-1.5 text-[0.9375rem] leading-relaxed
              placeholder:text-muted-foreground focus:outline-none
              disabled:opacity-50"
            onInput={adjustHeight}
            onKeyDown={handleKeyDown}
            disabled={disabled}
          />
          {isStreaming ? (
            <Button
              variant="destructive"
              size="icon"
              className="h-9 w-9 shrink-0 rounded-xl"
              onClick={onInterrupt}
              aria-label="Stop"
            >
              <Square className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button
              size="icon"
              className="h-9 w-9 shrink-0 rounded-xl"
              onClick={handleSend}
              disabled={disabled}
              aria-label="Send"
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
