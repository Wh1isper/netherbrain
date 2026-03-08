import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
}

export default function ThinkingBlock({ content, isStreaming }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(true);

  if (!content && !isStreaming) return null;

  return (
    <div className="mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-muted/60"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
        />
        <Brain className={`h-3 w-3 text-primary/60 ${isStreaming ? "animate-pulse" : ""}`} />
        <span>
          Thinking
          {isStreaming && <AnimatedDots />}
        </span>
      </button>
      {expanded && (
        <div
          className={`mt-1.5 ml-[18px] text-xs text-muted-foreground whitespace-pre-wrap pl-3 max-h-64 overflow-y-auto leading-relaxed border-l-2 ${
            isStreaming ? "border-primary/40 animate-pulse" : "border-primary/20"
          }`}
        >
          {content}
        </div>
      )}
    </div>
  );
}

/** Animated ellipsis that cycles through ., .., ... */
function AnimatedDots() {
  return (
    <span className="inline-block w-[1em] text-left overflow-hidden">
      <span className="animate-[thinking-dots_1.4s_infinite]">...</span>
    </span>
  );
}
