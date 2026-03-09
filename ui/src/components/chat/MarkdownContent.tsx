import { memo, useEffect, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";
import { highlightCode } from "@/lib/highlighter";
import { useAppStore } from "@/stores/app";
import ImageLightbox from "@/components/ImageLightbox";

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
    <div className="group relative my-3 rounded-xl border border-border/60 overflow-hidden bg-card shadow-sm">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3.5 py-1.5 bg-muted/60 border-b border-border/60">
        <span className="text-[11px] font-mono text-muted-foreground tracking-wide">
          {lang || "text"}
        </span>
        <button
          onClick={() => void handleCopy()}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors rounded px-1.5 py-0.5 hover:bg-muted"
          aria-label="Copy code"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-primary" />
              <span className="text-primary">Copied</span>
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
      <div className="overflow-x-auto text-sm [&_pre]:!m-0 [&_pre]:!rounded-none [&_pre]:!border-0 [&_pre]:p-3.5 [&_pre]:!bg-transparent [&_code]:!bg-transparent">
        {html ? (
          <div dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <pre className="p-3.5">
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
  return (
    <code className="rounded-md bg-muted/80 px-1.5 py-0.5 text-[0.85em] font-mono text-foreground/85">
      {children}
    </code>
  );
}

// ---------------------------------------------------------------------------
// MarkdownContent — uses the chatbot-optimised .chat-prose from index.css
// ---------------------------------------------------------------------------

interface MarkdownContentProps {
  content: string;
}

export default memo(function MarkdownContent({ content }: MarkdownContentProps) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  return (
    <div className="chat-prose max-w-none break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
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
              <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                {children}
              </a>
            );
          },
          // Images: clickable for lightbox
          img({ src, alt, ...props }) {
            return (
              <img
                src={src}
                alt={alt}
                {...props}
                className="cursor-pointer rounded-lg hover:opacity-90 transition-opacity max-h-96"
                onClick={() => src && setLightboxSrc(src)}
              />
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>

      <ImageLightbox
        src={lightboxSrc ?? ""}
        open={!!lightboxSrc}
        onClose={() => setLightboxSrc(null)}
      />
    </div>
  );
});
