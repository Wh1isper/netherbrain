import { memo, useEffect, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";
import { highlightCode } from "@/lib/highlighter";
import { useAppStore } from "@/stores/app";

// ---------------------------------------------------------------------------
// Code block with Shiki highlighting and copy button
// ---------------------------------------------------------------------------

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const theme = useAppStore((s) => s.theme);

  useEffect(() => {
    let cancelled = false;
    highlightCode(code, lang, theme).then((result) => {
      if (!cancelled) setHtml(result);
    });
    return () => {
      cancelled = true;
    };
  }, [code, lang, theme]);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  return (
    <div className="group relative my-3 rounded-lg border border-border overflow-hidden bg-muted/50">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-muted/80 border-b border-border">
        <span className="text-[11px] font-mono text-muted-foreground">{lang || "text"}</span>
        <button
          onClick={() => void handleCopy()}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Copy code"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3" />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      {/* Code content */}
      <div className="overflow-x-auto text-sm [&_pre]:!m-0 [&_pre]:!rounded-none [&_pre]:!border-0 [&_pre]:p-3 [&_pre]:!bg-transparent [&_code]:!bg-transparent">
        {html ? (
          <div dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <pre className="p-3">
            <code>{code}</code>
          </pre>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline code
// ---------------------------------------------------------------------------

function InlineCode({ children }: { children?: React.ReactNode }) {
  return <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono">{children}</code>;
}

// ---------------------------------------------------------------------------
// MarkdownContent
// ---------------------------------------------------------------------------

interface MarkdownContentProps {
  content: string;
}

export default memo(function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className="prose prose-sm dark:prose-invert max-w-none break-words
        prose-p:my-2 prose-headings:my-3 prose-ul:my-2 prose-ol:my-2
        prose-li:my-0.5 prose-blockquote:my-2 prose-pre:my-0 prose-hr:my-4
        prose-table:my-2 prose-img:my-2"
      components={{
        // Code blocks and inline code
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || "");
          const codeString = String(children).replace(/\n$/, "");

          // If it has a language class or contains newlines, render as block
          if (match || codeString.includes("\n")) {
            return <CodeBlock lang={match?.[1] ?? ""} code={codeString} />;
          }

          return <InlineCode {...props}>{children}</InlineCode>;
        },
        // Strip the wrapping <pre> since CodeBlock handles its own
        pre({ children }) {
          return <>{children}</>;
        },
        // Links open in new tab
        a({ children, href, ...props }) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline"
              {...props}
            >
              {children}
            </a>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
});
