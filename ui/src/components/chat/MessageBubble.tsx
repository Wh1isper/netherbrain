import { User, Bot } from "lucide-react";
import type { ChatMessage } from "@/stores/chat";
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
// User message
// ---------------------------------------------------------------------------

function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <div className="flex gap-3 px-4 py-4 justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary text-primary-foreground px-4 py-2.5">
        <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
      </div>
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted mt-0.5">
        <User className="h-4 w-4 text-muted-foreground" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Assistant message
// ---------------------------------------------------------------------------

function AssistantMessage({ message }: { message: ChatMessage }) {
  const hasContent = message.content.length > 0;
  const hasThinking = message.thinking.length > 0;
  const hasToolCalls = message.toolCalls.length > 0;
  const isEmpty = !hasContent && !hasThinking && !hasToolCalls;

  return (
    <div className="flex gap-3 px-4 py-4">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
        <Bot className="h-4 w-4 text-primary" />
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
          <span className="inline-block w-1.5 h-4 bg-foreground/70 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
        )}

        {/* Empty streaming state */}
        {isEmpty && message.isStreaming && (
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <span className="inline-block w-1.5 h-4 bg-foreground/40 animate-pulse rounded-sm" />
          </div>
        )}
      </div>
    </div>
  );
}
