import { useRef, useState, useEffect, useCallback } from "react";
import { ArrowUp, Square, Paperclip, X, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatFileSize, isImageMime, fileToBase64 } from "@/lib/utils";
import type { InputPart } from "@/api/types";
import type { StreamingState } from "@/stores/chat";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_INLINE_BYTES = 20 * 1024 * 1024; // 20 MB for images (inline)
const MAX_EPHEMERAL_BYTES = 100 * 1024 * 1024; // 100 MB for other files
const MAX_ATTACHMENTS = 10;

// ---------------------------------------------------------------------------
// Local attachment type (pre-send, holds File + preview URL)
// ---------------------------------------------------------------------------

interface Attachment {
  id: string;
  file: File;
  previewUrl: string | null; // object URL for images
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ChatInputProps {
  onSend: (text: string, attachments?: InputPart[]) => void;
  onInterrupt: () => void;
  streamingState: StreamingState;
  disabled?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatInput({
  onSend,
  onInterrupt,
  streamingState,
  disabled,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  // Clean up object URLs on unmount
  useEffect(() => {
    return () => {
      attachments.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
    };
    // Only run cleanup on unmount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Clear error after 4 seconds
  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(null), 4000);
    return () => clearTimeout(t);
  }, [error]);

  // -----------------------------------------------------------------------
  // Attachment helpers
  // -----------------------------------------------------------------------

  const addFiles = useCallback(
    (files: File[]) => {
      setError(null);
      const remaining = MAX_ATTACHMENTS - attachments.length;
      if (remaining <= 0) {
        setError(`Maximum ${MAX_ATTACHMENTS} attachments allowed`);
        return;
      }

      const toAdd = files.slice(0, remaining);
      const newAttachments: Attachment[] = [];

      for (const file of toAdd) {
        const isImage = isImageMime(file.type);
        const limit = isImage ? MAX_INLINE_BYTES : MAX_EPHEMERAL_BYTES;
        if (file.size > limit) {
          setError(
            `${file.name} is too large (${formatFileSize(file.size)}, limit: ${formatFileSize(limit)})`,
          );
          continue;
        }
        newAttachments.push({
          id: crypto.randomUUID(),
          file,
          previewUrl: isImage ? URL.createObjectURL(file) : null,
        });
      }

      if (newAttachments.length > 0) {
        setAttachments((prev) => [...prev, ...newAttachments]);
      }
    },
    [attachments.length],
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const removed = prev.find((a) => a.id === id);
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
      return prev.filter((a) => a.id !== id);
    });
  }, []);

  // -----------------------------------------------------------------------
  // Convert attachments to InputPart[]
  // -----------------------------------------------------------------------

  const buildInputParts = useCallback(async (): Promise<InputPart[]> => {
    const parts: InputPart[] = [];
    for (const att of attachments) {
      const base64 = await fileToBase64(att.file);
      const isImage = isImageMime(att.file.type);
      parts.push({
        type: "binary",
        data: base64,
        mime: att.file.type || "application/octet-stream",
        storage: isImage ? "inline" : "ephemeral",
      });
    }
    return parts;
  }, [attachments]);

  // -----------------------------------------------------------------------
  // Send
  // -----------------------------------------------------------------------

  const handleSend = useCallback(async () => {
    const el = textareaRef.current;
    if (!el) return;
    const text = el.value.trim();
    if (!text && attachments.length === 0) return;

    const parts = attachments.length > 0 ? await buildInputParts() : undefined;
    onSend(text, parts);

    // Clear state
    el.value = "";
    el.style.height = "auto";
    attachments.forEach((a) => {
      if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
    });
    setAttachments([]);
  }, [onSend, attachments, buildInputParts]);

  // -----------------------------------------------------------------------
  // Event handlers
  // -----------------------------------------------------------------------

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void handleSend();
      }
    },
    [handleSend],
  );

  // Clipboard paste -- intercept images
  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;

      const imageFiles: File[] = [];
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) imageFiles.push(file);
        }
      }

      if (imageFiles.length > 0) {
        e.preventDefault(); // prevent pasting image as text
        addFiles(imageFiles);
      }
    },
    [addFiles],
  );

  // Drag and drop
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) addFiles(files);
    },
    [addFiles],
  );

  // File picker
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      if (files.length > 0) addFiles(files);
      // Reset input so re-selecting same file works
      e.target.value = "";
    },
    [addFiles],
  );

  const hasAttachments = attachments.length > 0;
  const canAttach = !isStreaming && attachments.length < MAX_ATTACHMENTS;

  return (
    <div className="bg-background px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div
          className={`flex flex-col rounded-2xl border bg-card px-3 py-2 shadow-sm transition-all focus-within:shadow-md focus-within:border-primary/20 ${
            dragOver ? "border-primary border-dashed bg-primary/5" : "border-border"
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {/* Attachment preview strip */}
          {hasAttachments && (
            <div className="flex gap-2 overflow-x-auto pb-2 mb-1 scrollbar-thin">
              {attachments.map((att) =>
                att.previewUrl ? (
                  <div key={att.id} className="relative shrink-0 group">
                    <img
                      src={att.previewUrl}
                      alt={att.file.name}
                      className="h-16 w-16 rounded-lg object-cover"
                    />
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-foreground/80 text-background opacity-0 group-hover:opacity-100 transition-opacity"
                      aria-label="Remove"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ) : (
                  <div
                    key={att.id}
                    className="relative shrink-0 flex items-center gap-2 rounded-lg bg-muted px-3 py-2 group"
                  >
                    <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm truncate max-w-[140px]">{att.file.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatFileSize(att.file.size)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="flex h-5 w-5 items-center justify-center rounded-full bg-foreground/80 text-background opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                      aria-label="Remove"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ),
              )}
            </div>
          )}

          {/* Input row */}
          <div className="flex items-end gap-2">
            {/* Attach button */}
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 shrink-0 rounded-xl text-muted-foreground hover:text-foreground"
              onClick={() => fileInputRef.current?.click()}
              disabled={!canAttach || disabled}
              aria-label="Attach file"
            >
              <Paperclip className="h-4 w-4" />
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              rows={1}
              placeholder={
                isStreaming ? "Send a message to guide the agent..." : "Send a message..."
              }
              className="flex-1 resize-none bg-transparent px-1 py-1.5 text-[0.9375rem] leading-relaxed
                placeholder:text-muted-foreground focus:outline-none
                disabled:opacity-50"
              onInput={adjustHeight}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              disabled={disabled}
            />

            {/* Send / Stop button */}
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
                onClick={() => void handleSend()}
                disabled={disabled}
                aria-label="Send"
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {/* Error toast */}
        {error && <p className="mt-1.5 text-xs text-destructive text-center">{error}</p>}
      </div>
    </div>
  );
}
