import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Bot, Loader2 } from "lucide-react";
import type { ChatMessage } from "@/stores/chat";
import MessageBubble from "./MessageBubble";
import { AsyncResultPanel } from "./AsyncAgentPanel";

interface MessageListProps {
  messages: ChatMessage[];
  hasMoreMessages?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
}

export default function MessageList({
  messages,
  hasMoreMessages = false,
  loadingMore = false,
  onLoadMore,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Auto-scroll to bottom when new content arrives (streaming)
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, autoScroll]);

  // Detect if user has scrolled up (disable auto-scroll)
  const handleScroll = useCallback(() => {
    const el = scrollAreaRef.current?.querySelector("[data-radix-scroll-area-viewport]");
    if (!el) return;

    const { scrollTop, scrollHeight, clientHeight } = el;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    // Re-enable auto-scroll if user scrolls back near bottom
    setAutoScroll(distanceFromBottom < 80);
  }, []);

  // Attach scroll listener to the viewport element
  useEffect(() => {
    const el = scrollAreaRef.current?.querySelector("[data-radix-scroll-area-viewport]");
    if (!el) return;
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  // Intersection observer for loading older messages on scroll-up
  useEffect(() => {
    if (!hasMoreMessages || loadingMore || !onLoadMore) return;

    const sentinel = topSentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onLoadMore();
        }
      },
      {
        root: scrollAreaRef.current?.querySelector("[data-radix-scroll-area-viewport]"),
        threshold: 0,
        rootMargin: "200px 0px 0px 0px", // trigger 200px before reaching the top
      },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMoreMessages, loadingMore, onLoadMore]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="text-center space-y-3">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 mx-auto">
            <Bot className="h-6 w-6 text-primary" />
          </div>
          <div className="space-y-1">
            <p className="text-base font-medium text-foreground">Start a conversation</p>
            <p className="text-sm text-muted-foreground">Send a message below to begin.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1 min-h-0" ref={scrollAreaRef}>
      <div className="mx-auto max-w-3xl py-4">
        {/* Top sentinel for infinite scroll */}
        <div ref={topSentinelRef} />

        {/* Loading indicator for older messages */}
        {loadingMore && (
          <div className="flex items-center justify-center py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            Loading older messages...
          </div>
        )}

        <MessageRenderer messages={messages} />
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// MessageRenderer -- groups fire-continuation messages into panels
// ---------------------------------------------------------------------------

function MessageRenderer({ messages }: { messages: ChatMessage[] }) {
  const elements = useMemo(() => {
    const result: React.ReactNode[] = [];
    let i = 0;

    while (i < messages.length) {
      const msg = messages[i];

      // Group fire-continuation user + assistant into a single panel
      if (msg.isFireContinuation && msg.role === "user") {
        const userMsg = msg;
        // Look ahead for the following fire-continuation assistant message
        const nextMsg = i + 1 < messages.length ? messages[i + 1] : undefined;
        const assistantMsg =
          nextMsg?.isFireContinuation && nextMsg.role === "assistant" ? nextMsg : undefined;

        result.push(
          <AsyncResultPanel
            key={userMsg.id}
            userMessage={userMsg}
            assistantMessage={assistantMsg}
          />,
        );
        i += assistantMsg ? 2 : 1;
        continue;
      }

      // Skip orphaned fire-continuation assistant messages (already grouped)
      if (msg.isFireContinuation && msg.role === "assistant") {
        // Render as standalone panel with empty user message
        result.push(
          <AsyncResultPanel
            key={msg.id}
            userMessage={{ ...msg, role: "user", content: "", fireInputText: "" }}
            assistantMessage={msg}
          />,
        );
        i++;
        continue;
      }

      // Normal message
      result.push(<MessageBubble key={msg.id} message={msg} />);
      i++;
    }

    return result;
  }, [messages]);

  return <>{elements}</>;
}
