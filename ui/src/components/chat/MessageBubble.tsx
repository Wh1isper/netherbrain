import { useState } from "react";
import { User, Bot, FileText, Link, FolderOpen } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import type { ChatMessage } from "@/stores/chat";
import type { InputPart } from "@/api/types";
import { formatFileSize, isImageMime } from "@/lib/utils";
import MarkdownContent from "./MarkdownContent";
import ToolCallCard from "./ToolCallCard";
import ThinkingBlock from "./ThinkingBlock";

interface MessageBubbleProps {
  message: ChatMessage;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") {
    return <UserMessage message={message} />;
  }
  return <AssistantMessage message={message} />;
}

// ---------------------------------------------------------------------------
// User message -- brand-colored bubble, right-aligned
// ---------------------------------------------------------------------------

function UserMessage({ message }: { message: ChatMessage }) {
  const hasText = message.content.length > 0;
  const hasAttachments = message.attachments.length > 0;

  return (
    <div className="flex gap-3 px-4 py-3 justify-end">
      <div className="max-w-[80%] flex flex-col items-end gap-2">
        {/* Attachment display */}
        {hasAttachments && (
          <div className="flex flex-wrap gap-1.5 justify-end">
            {message.attachments.map((part, i) => (
              <AttachmentBadge key={i} part={part} />
            ))}
          </div>
        )}

        {/* Text bubble */}
        {hasText && (
          <div className="rounded-2xl rounded-br-md bg-primary text-primary-foreground px-4 py-2.5 shadow-sm">
            <p className="text-[0.9375rem] leading-relaxed whitespace-pre-wrap break-words">
              {message.content}
            </p>
          </div>
        )}
      </div>
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
        <User className="h-3.5 w-3.5 text-primary" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Attachment badge -- renders a single non-text InputPart
// ---------------------------------------------------------------------------

function AttachmentBadge({ part }: { part: InputPart }) {
  // Binary image -> thumbnail
  if (part.type === "binary" && part.mime && isImageMime(part.mime) && part.data) {
    return <ImageThumbnail data={part.data} mime={part.mime} />;
  }

  // Binary non-image -> file badge
  if (part.type === "binary") {
    const sizeBytes = part.data ? Math.floor((part.data.length * 3) / 4) : 0;
    return (
      <div className="flex items-center gap-1.5 rounded-md bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
        <FileText className="h-3 w-3 shrink-0" />
        <span>{part.mime ?? "file"}</span>
        {sizeBytes > 0 && <span>({formatFileSize(sizeBytes)})</span>}
      </div>
    );
  }

  // URL -> link badge
  if (part.type === "url" && part.url) {
    return (
      <a
        href={part.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-1.5 rounded-md bg-muted/60 px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Link className="h-3 w-3 shrink-0" />
        <span className="truncate max-w-[200px]">{part.url}</span>
      </a>
    );
  }

  // File path -> path badge
  if (part.type === "file" && part.path) {
    return (
      <div className="flex items-center gap-1.5 rounded-md bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
        <FolderOpen className="h-3 w-3 shrink-0" />
        <span className="truncate max-w-[200px]">{part.path}</span>
      </div>
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// Image thumbnail with lightbox
// ---------------------------------------------------------------------------

function ImageThumbnail({ data, mime }: { data: string; mime: string }) {
  const [open, setOpen] = useState(false);
  const src = `data:${mime};base64,${data}`;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="cursor-pointer rounded-lg overflow-hidden"
      >
        <img
          src={src}
          alt="Attached image"
          className="rounded-lg max-h-48 max-w-[280px] object-cover"
        />
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[90vw] max-h-[90vh] p-2">
          <DialogTitle className="sr-only">Image preview</DialogTitle>
          <img
            src={src}
            alt="Full size preview"
            className="max-w-full max-h-[85vh] object-contain mx-auto rounded-lg"
          />
        </DialogContent>
      </Dialog>
    </>
  );
}

// ---------------------------------------------------------------------------
// Assistant message -- clean layout, no background
// ---------------------------------------------------------------------------

function AssistantMessage({ message }: { message: ChatMessage }) {
  const hasContent = message.content.length > 0;
  const hasThinking = message.thinking.length > 0;
  const hasToolCalls = message.toolCalls.length > 0;
  const isEmpty = !hasContent && !hasThinking && !hasToolCalls;

  return (
    <div className="flex gap-3 px-4 py-3">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
        <Bot className="h-3.5 w-3.5 text-primary" />
      </div>
      <div className="min-w-0 flex-1 max-w-[90%]">
        {/* Thinking section (collapsed by default) */}
        {(hasThinking || message.isStreaming) && (
          <ThinkingBlock
            content={message.thinking}
            isStreaming={message.isStreaming && !hasContent}
          />
        )}

        {/* Tool calls */}
        {hasToolCalls && (
          <div className="mb-2">
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}

        {/* Text content */}
        {hasContent && <MarkdownContent content={message.content} />}

        {/* Streaming cursor */}
        {message.isStreaming && hasContent && (
          <span className="inline-block w-1.5 h-4 bg-primary/60 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
        )}

        {/* Empty streaming state */}
        {isEmpty && message.isStreaming && (
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <span className="inline-block w-1.5 h-4 bg-primary/40 animate-pulse rounded-sm" />
          </div>
        )}
      </div>
    </div>
  );
}
