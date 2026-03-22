import { useState, Fragment } from "react";
import { User, Bot, FileText, Link, FolderOpen, ChevronRight, Zap } from "lucide-react";
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
  if (message.isFireContinuation) {
    return <FireContinuationMessage message={message} />;
  }
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
  const hasBlocks = message.blocks.length > 0;
  const hasContent = message.content.length > 0;
  const hasThinking = message.thinkingBlocks.length > 0;
  const hasToolCalls = message.toolCalls.length > 0;
  const isEmpty = !hasContent && !hasThinking && !hasToolCalls;

  return (
    <div className="flex gap-3 px-4 py-3">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
        <Bot className="h-3.5 w-3.5 text-primary" />
      </div>
      <div className="min-w-0 flex-1 max-w-[90%]">
        {hasBlocks ? (
          <>
            {message.blocks.map((block, i) => {
              const isLastBlock = i === message.blocks.length - 1;
              const isActive = message.isStreaming && isLastBlock;

              switch (block.type) {
                case "thinking":
                  return (
                    <ThinkingBlock
                      key={`t-${block.index}`}
                      blocks={[message.thinkingBlocks[block.index]]}
                      isStreaming={isActive}
                    />
                  );
                case "text": {
                  const text = message.textBlocks[block.index];
                  return (
                    <Fragment key={`x-${block.index}`}>
                      {text && <MarkdownContent content={text} />}
                      {isActive && text && (
                        <span className="inline-block w-1.5 h-4 bg-primary/60 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
                      )}
                    </Fragment>
                  );
                }
                case "tool_call": {
                  const tc = message.toolCalls.find((t) => t.id === block.id);
                  return tc ? <ToolCallCard key={tc.id} toolCall={tc} /> : null;
                }
              }
            })}
          </>
        ) : (
          /* Fallback for messages without blocks (backward compat) */
          <>
            {(hasThinking || message.isStreaming) && (
              <ThinkingBlock
                blocks={message.thinkingBlocks}
                isStreaming={message.isStreaming && !hasContent}
              />
            )}

            {hasToolCalls && (
              <div className="mb-2">
                {message.toolCalls.map((tc) => (
                  <ToolCallCard key={tc.id} toolCall={tc} />
                ))}
              </div>
            )}

            {hasContent && <MarkdownContent content={message.content} />}

            {message.isStreaming && hasContent && (
              <span className="inline-block w-1.5 h-4 bg-primary/60 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
            )}
          </>
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

// ---------------------------------------------------------------------------
// Fire-continuation message -- collapsed async subagent result
// ---------------------------------------------------------------------------

function FireContinuationMessage({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const hasContent = message.content.length > 0;

  // Skip user messages from fire-continuation (they have no meaningful text)
  if (message.role === "user") return null;

  if (!hasContent && message.toolCalls.length === 0) return null;

  return (
    <div className="px-4 py-1.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors rounded-md px-2 py-1 -ml-2 hover:bg-muted/60"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
        />
        <Zap className="h-3 w-3 text-primary/60" />
        <span>Async agent result</span>
      </button>
      {expanded && (
        <div className="mt-2 ml-5 pl-3 border-l-2 border-primary/20">
          <div className="flex gap-3">
            <div className="min-w-0 flex-1 max-w-[90%]">
              {message.blocks.length > 0 ? (
                message.blocks.map((block) => {
                  switch (block.type) {
                    case "thinking":
                      return (
                        <ThinkingBlock
                          key={`t-${block.index}`}
                          blocks={[message.thinkingBlocks[block.index]]}
                          isStreaming={false}
                        />
                      );
                    case "text": {
                      const text = message.textBlocks[block.index];
                      return text ? (
                        <MarkdownContent key={`x-${block.index}`} content={text} />
                      ) : null;
                    }
                    case "tool_call": {
                      const tc = message.toolCalls.find((t) => t.id === block.id);
                      return tc ? <ToolCallCard key={tc.id} toolCall={tc} /> : null;
                    }
                  }
                })
              ) : (
                /* Fallback for messages without blocks */
                <>
                  {message.thinkingBlocks.length > 0 && (
                    <ThinkingBlock blocks={message.thinkingBlocks} isStreaming={false} />
                  )}
                  {message.toolCalls.length > 0 && (
                    <div className="mb-2">
                      {message.toolCalls.map((tc) => (
                        <ToolCallCard key={tc.id} toolCall={tc} />
                      ))}
                    </div>
                  )}
                  {hasContent && <MarkdownContent content={message.content} />}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
