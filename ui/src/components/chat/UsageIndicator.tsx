import { Activity } from "lucide-react";
import type { UsageData } from "@/stores/chat";

interface UsageIndicatorProps {
  usage: UsageData | null;
  /** Whether the agent is currently streaming (controls animation). */
  streaming?: boolean;
}

/** Format token count with K/M suffix for compact display. */
function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(0)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function UsageIndicator({ usage, streaming = false }: UsageIndicatorProps) {
  if (!usage) return null;

  const entries = Object.entries(usage.modelUsages);
  if (entries.length === 0) return null;

  // Compute totals across all models.
  let totalInput = 0;
  let totalOutput = 0;
  let totalCacheRead = 0;
  let totalRequests = 0;

  for (const [, u] of entries) {
    totalInput += u.inputTokens;
    totalOutput += u.outputTokens;
    totalCacheRead += u.cacheReadTokens;
    totalRequests += u.requests;
  }

  const totalTokens = totalInput + totalOutput;

  return (
    <div className="flex items-center justify-center gap-3 px-4 py-1 text-[0.6875rem] text-muted-foreground/70 select-none">
      <Activity className={`h-3 w-3 shrink-0 ${streaming ? "animate-pulse" : ""}`} />
      <span>
        {formatTokens(totalTokens)} tokens
        <span className="mx-1 opacity-40">|</span>
        {formatTokens(totalInput)} in
        {totalCacheRead > 0 && (
          <span className="opacity-60"> ({formatTokens(totalCacheRead)} cached)</span>
        )}
        <span className="mx-1 opacity-40">|</span>
        {formatTokens(totalOutput)} out
        <span className="mx-1 opacity-40">|</span>
        {totalRequests} req{totalRequests !== 1 ? "s" : ""}
      </span>
      {entries.length > 1 && <span className="opacity-50">({entries.length} models)</span>}
    </div>
  );
}
