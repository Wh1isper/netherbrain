import { useState, useRef, useCallback } from "react";
import {
  ChevronRight,
  Zap,
  CheckCircle2,
  XCircle,
  Loader2,
  MessageSquare,
  Square,
  Send,
} from "lucide-react";
import type { ChatMessage, SubagentInfo } from "@/stores/chat";
import { steerSession, interruptSession } from "@/api/sessions";
import MarkdownContent from "./MarkdownContent";
import ToolCallCard from "./ToolCallCard";
import ThinkingBlock from "./ThinkingBlock";

// ---------------------------------------------------------------------------
// Parse mailbox prompt text to extract subagent info
// ---------------------------------------------------------------------------

interface ParsedSubagent {
  name: string;
  status: "completed" | "failed";
  content: string;
}

function parseMailboxPrompt(text: string): ParsedSubagent[] {
  if (!text) return [];

  // Single subagent format:
  // Async subagent 'name' (session: xxx) completed:\ncontent
  // Async subagent 'name' (session: xxx) failed.
  const singleMatch = text.match(/^Async subagent '([^']+)' \(session: [^)]+\) (completed|failed)/);
  if (singleMatch) {
    const name = singleMatch[1];
    const status = singleMatch[2] as "completed" | "failed";
    const content =
      status === "completed"
        ? text.replace(/^Async subagent '[^']+' \(session: [^)]+\) completed:\n?/, "")
        : "";
    return [{ name, status, content }];
  }

  // Multiple subagents format:
  // Async subagent results:\n\n## name [status] (session: xxx)\ncontent\n...
  if (text.startsWith("Async subagent results:")) {
    const results: ParsedSubagent[] = [];
    const sections = text.split(/\n## /).slice(1); // skip header
    for (const section of sections) {
      const headerMatch = section.match(
        /^([^[]+)\s+\[(completed|failed)]\s+\(session: [^)]+\)\n?([\s\S]*)/,
      );
      if (headerMatch) {
        results.push({
          name: headerMatch[1].trim(),
          status: headerMatch[2] as "completed" | "failed",
          content: headerMatch[3].trim(),
        });
      }
    }
    return results;
  }

  return [];
}

// ---------------------------------------------------------------------------
// Panel for fire-continuation messages in the message flow
// ---------------------------------------------------------------------------

interface AsyncResultPanelProps {
  /** The user message with fireInputText (mailbox prompt). */
  userMessage: ChatMessage;
  /** The assistant response message. */
  assistantMessage?: ChatMessage;
}

export function AsyncResultPanel({ userMessage, assistantMessage }: AsyncResultPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const parsed = parseMailboxPrompt(userMessage.fireInputText ?? "");

  if (parsed.length === 0 && !assistantMessage) return null;

  const completedCount = parsed.filter((s) => s.status === "completed").length;
  const failedCount = parsed.filter((s) => s.status === "failed").length;

  return (
    <div className="px-4 py-2">
      <div className="rounded-xl border border-border/60 bg-card/50 overflow-hidden">
        {/* Header */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 w-full px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
        >
          <ChevronRight
            className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
          />
          <Zap className="h-3.5 w-3.5 shrink-0 text-primary/70" />
          <span className="font-medium">Async agent results</span>
          <span className="text-xs">
            ({completedCount} completed{failedCount > 0 ? `, ${failedCount} failed` : ""})
          </span>
        </button>

        {/* Expanded content */}
        {expanded && (
          <div className="border-t border-border/40 px-3 py-2 space-y-3">
            {/* Subagent list */}
            {parsed.length > 0 && (
              <div className="space-y-2">
                {parsed.map((sub, i) => (
                  <SubagentResultCard key={i} subagent={sub} />
                ))}
              </div>
            )}

            {/* Assistant response */}
            {assistantMessage &&
              (assistantMessage.content || assistantMessage.toolCalls.length > 0) && (
                <div className="border-t border-border/30 pt-2">
                  <p className="text-xs font-medium text-muted-foreground mb-1.5">Agent response</p>
                  <div className="pl-2">
                    {assistantMessage.blocks.length > 0 ? (
                      assistantMessage.blocks.map((block) => {
                        switch (block.type) {
                          case "thinking":
                            return (
                              <ThinkingBlock
                                key={`t-${block.index}`}
                                blocks={[assistantMessage.thinkingBlocks[block.index]]}
                                isStreaming={false}
                              />
                            );
                          case "text": {
                            const text = assistantMessage.textBlocks[block.index];
                            return text ? (
                              <MarkdownContent key={`x-${block.index}`} content={text} />
                            ) : null;
                          }
                          case "tool_call": {
                            const tc = assistantMessage.toolCalls.find((t) => t.id === block.id);
                            return tc ? <ToolCallCard key={tc.id} toolCall={tc} /> : null;
                          }
                        }
                      })
                    ) : (
                      /* Fallback for messages without blocks */
                      <>
                        {assistantMessage.thinkingBlocks.length > 0 && (
                          <ThinkingBlock
                            blocks={assistantMessage.thinkingBlocks}
                            isStreaming={false}
                          />
                        )}
                        {assistantMessage.toolCalls.length > 0 && (
                          <div className="mb-2">
                            {assistantMessage.toolCalls.map((tc) => (
                              <ToolCallCard key={tc.id} toolCall={tc} />
                            ))}
                          </div>
                        )}
                        {assistantMessage.content && (
                          <MarkdownContent content={assistantMessage.content} />
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subagent result card (within the expanded panel)
// ---------------------------------------------------------------------------

function SubagentResultCard({ subagent }: { subagent: ParsedSubagent }) {
  const [showContent, setShowContent] = useState(false);
  const hasContent = subagent.content.length > 0;

  return (
    <div className="rounded-lg border border-border/40 bg-background/50">
      <button
        onClick={() => hasContent && setShowContent(!showContent)}
        className={`flex items-center gap-2 w-full px-2.5 py-1.5 text-xs ${
          hasContent ? "cursor-pointer hover:bg-muted/30" : "cursor-default"
        } transition-colors`}
      >
        {subagent.status === "completed" ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-primary shrink-0" />
        ) : (
          <XCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
        )}
        <span className="font-medium text-foreground">{subagent.name}</span>
        <span className="text-muted-foreground">{subagent.status}</span>
        {hasContent && (
          <ChevronRight
            className={`h-3 w-3 ml-auto shrink-0 text-muted-foreground transition-transform duration-200 ${
              showContent ? "rotate-90" : ""
            }`}
          />
        )}
      </button>
      {showContent && hasContent && (
        <div className="px-2.5 pb-2 text-xs text-muted-foreground border-t border-border/30 pt-1.5">
          <pre className="whitespace-pre-wrap break-words max-h-48 overflow-y-auto leading-relaxed">
            {subagent.content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Streaming subagent status panel (shown during active session)
// ---------------------------------------------------------------------------

interface StreamingSubagentPanelProps {
  subagents: SubagentInfo[];
}

export function StreamingSubagentPanel({ subagents }: StreamingSubagentPanelProps) {
  if (subagents.length === 0) return null;

  return (
    <div className="px-4 py-1">
      <div className="rounded-xl border border-border/60 bg-card/50 px-3 py-2">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1.5">
          <Zap className="h-3 w-3 text-primary/70" />
          <span className="font-medium">Async agents</span>
        </div>
        <div className="space-y-1">
          {subagents.map((s) => (
            <StreamingSubagentRow key={s.id} subagent={s} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Individual subagent row with steer / interrupt controls
// ---------------------------------------------------------------------------

function StreamingSubagentRow({ subagent }: { subagent: SubagentInfo }) {
  const [showSteer, setShowSteer] = useState(false);
  const [steerText, setSteerText] = useState("");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const isRunning = subagent.status === "started";

  const handleSteer = useCallback(async () => {
    const text = steerText.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      await steerSession(subagent.id, { input: [{ type: "text", text }] });
      setSteerText("");
      setShowSteer(false);
    } catch {
      // best effort -- subagent may have finished
    } finally {
      setSending(false);
    }
  }, [subagent.id, steerText, sending]);

  const handleInterrupt = useCallback(async () => {
    try {
      await interruptSession(subagent.id);
    } catch {
      // best effort
    }
  }, [subagent.id]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSteer();
      } else if (e.key === "Escape") {
        setShowSteer(false);
        setSteerText("");
      }
    },
    [handleSteer],
  );

  return (
    <div>
      <div className="flex items-center gap-2 text-xs">
        {isRunning ? (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground shrink-0" />
        ) : subagent.status === "completed" ? (
          <CheckCircle2 className="h-3 w-3 text-primary shrink-0" />
        ) : (
          <XCircle className="h-3 w-3 text-destructive shrink-0" />
        )}
        <span className="text-foreground">{subagent.name}</span>
        <span className="text-muted-foreground">{subagent.status}</span>

        {isRunning && (
          <div className="flex items-center gap-0.5 ml-auto">
            <button
              onClick={() => {
                setShowSteer(!showSteer);
                if (!showSteer) setTimeout(() => inputRef.current?.focus(), 0);
              }}
              className="p-0.5 rounded hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
              title="Steer subagent"
            >
              <MessageSquare className="h-3 w-3" />
            </button>
            <button
              onClick={handleInterrupt}
              className="p-0.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
              title="Interrupt subagent"
            >
              <Square className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>

      {showSteer && isRunning && (
        <div className="flex items-center gap-1.5 mt-1 ml-5">
          <input
            ref={inputRef}
            type="text"
            value={steerText}
            onChange={(e) => setSteerText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Steer this agent..."
            className="flex-1 h-6 px-2 text-xs rounded-md border border-border/60 bg-background/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary/40"
            disabled={sending}
          />
          <button
            onClick={handleSteer}
            disabled={!steerText.trim() || sending}
            className="p-1 rounded hover:bg-muted/60 text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="h-3 w-3" />
          </button>
        </div>
      )}
    </div>
  );
}
