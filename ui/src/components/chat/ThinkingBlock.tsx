import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
}

export default function ThinkingBlock({ content, isStreaming }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(false);

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
        <Brain className="h-3 w-3 text-primary/60" />
        <span>{isStreaming ? "Thinking..." : "Thinking"}</span>
      </button>
      {expanded && (
        <div className="mt-1.5 ml-[18px] text-xs text-muted-foreground whitespace-pre-wrap border-l-2 border-primary/20 pl-3 max-h-64 overflow-y-auto leading-relaxed">
          {content}
          {isStreaming && <span className="animate-pulse text-primary/60">|</span>}
        </div>
      )}
    </div>
  );
}
