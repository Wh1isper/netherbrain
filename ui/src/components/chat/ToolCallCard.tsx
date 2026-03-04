import { useState } from "react";
import { ChevronRight, Check, AlertTriangle, X, Loader2 } from "lucide-react";
import type { ToolCall } from "@/stores/chat";

interface ToolCallCardProps {
  toolCall: ToolCall;
}

const statusConfig = {
  running: { icon: Loader2, color: "text-blue-500", spin: true },
  complete: { icon: Check, color: "text-green-500", spin: false },
  retry: { icon: AlertTriangle, color: "text-yellow-500", spin: false },
  cancel: { icon: X, color: "text-red-500", spin: false },
} as const;

function formatArgs(args: string): string {
  try {
    return JSON.stringify(JSON.parse(args), null, 2);
  } catch {
    return args;
  }
}

function makeSummary(toolCall: ToolCall): string {
  if (toolCall.status === "running") return "Running...";

  // Try to extract a meaningful summary from args
  try {
    const parsed = JSON.parse(toolCall.args);
    if (parsed.command) return String(parsed.command).slice(0, 80);
    if (parsed.query) return String(parsed.query).slice(0, 80);
    if (parsed.file_path) return String(parsed.file_path);
    if (parsed.path) return String(parsed.path);
    if (parsed.url) return String(parsed.url).slice(0, 80);
    if (parsed.pattern) return String(parsed.pattern).slice(0, 80);
  } catch {
    // ignore
  }

  return "Done";
}

export default function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const config = statusConfig[toolCall.status];
  const Icon = config.icon;
  const summary = makeSummary(toolCall);

  return (
    <div className="my-1.5 rounded-lg border border-border bg-muted/30 text-sm overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/50 transition-colors"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200 ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <Icon
          className={`h-3.5 w-3.5 shrink-0 ${config.color} ${config.spin ? "animate-spin" : ""}`}
        />
        <span className="font-mono text-xs font-medium">{toolCall.name}</span>
        {!expanded && (
          <span className="truncate text-xs text-muted-foreground ml-1">{summary}</span>
        )}
      </button>
      {expanded && (
        <div className="border-t border-border px-3 py-2 space-y-2">
          {toolCall.args && (
            <div>
              <div className="text-[11px] font-medium text-muted-foreground mb-1 uppercase tracking-wide">
                Arguments
              </div>
              <pre className="text-xs bg-muted rounded-md p-2 overflow-x-auto max-h-48 overflow-y-auto">
                {formatArgs(toolCall.args)}
              </pre>
            </div>
          )}
          {toolCall.result !== undefined && (
            <div>
              <div className="text-[11px] font-medium text-muted-foreground mb-1 uppercase tracking-wide">
                Result
              </div>
              <pre className="text-xs bg-muted rounded-md p-2 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap break-words">
                {toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
