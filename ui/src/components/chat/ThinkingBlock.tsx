import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";

interface ThinkingBlockProps {
  /** Array of thinking blocks (one per reasoning cycle). */
  blocks: string[];
  isStreaming?: boolean;
}

export default function ThinkingBlock({ blocks, isStreaming }: ThinkingBlockProps) {
  if (blocks.length === 0 && !isStreaming) return null;

  // When streaming with no blocks yet, show a single pulsing indicator
  if (blocks.length === 0 && isStreaming) {
    return (
      <div className="mb-3">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground px-1.5 py-0.5 -ml-1.5">
          <Brain className="h-3 w-3 text-primary/60 animate-pulse" />
          <span>
            Thinking
            <AnimatedDots />
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-3 space-y-1">
      {blocks.map((content, index) => {
        const isLastBlock = index === blocks.length - 1;
        const isBlockStreaming = isStreaming && isLastBlock;
        return (
          <SingleThinkingBlock
            key={index}
            content={content}
            index={index}
            total={blocks.length}
            isStreaming={isBlockStreaming}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single collapsible thinking block
// ---------------------------------------------------------------------------

function SingleThinkingBlock({
  content,
  index,
  total,
  isStreaming,
}: {
  content: string;
  index: number;
  total: number;
  isStreaming?: boolean;
}) {
  const [expanded, setExpanded] = useState(true);

  if (!content && !isStreaming) return null;

  const label = total > 1 ? `Thinking (${index + 1}/${total})` : "Thinking";

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-muted/60"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
        />
        <Brain className={`h-3 w-3 text-primary/60 ${isStreaming ? "animate-pulse" : ""}`} />
        <span>
          {label}
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
