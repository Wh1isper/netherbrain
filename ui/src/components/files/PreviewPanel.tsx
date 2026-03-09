/**
 * PreviewPanel -- file content viewer with Shiki syntax highlighting.
 *
 * Reuses the same highlightCode / theme pattern as MarkdownContent CodeBlock.
 * Line numbers are rendered via CSS counters on Shiki's .line spans
 * (see the .code-viewer rule in index.css).
 */

import { useEffect, useState, useRef, useCallback } from "react";
import {
  File,
  Download,
  Edit3,
  Eye,
  Save,
  X,
  ArrowLeft,
  AlertCircle,
  Copy,
  Check,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { highlightCode } from "@/lib/highlighter";
import { useAppStore } from "@/stores/app";
import { useFilesStore } from "@/stores/files";
import { getDownloadUrl } from "@/api/files";
import { isTextFile, isImageFile, detectLanguage, formatBytes, formatDate } from "./file-utils";

// ---------------------------------------------------------------------------
// Syntax-highlighted code viewer
// ---------------------------------------------------------------------------

function CodeViewer({ code, fileName }: { code: string; fileName: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const theme = useAppStore((s) => s.theme);
  const lang = detectLanguage(fileName);

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
    <div className="relative group">
      {/* Copy button -- top-right, visible on hover */}
      <button
        onClick={() => void handleCopy()}
        className="absolute top-2 right-2 z-10 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors rounded-lg px-2 py-1 bg-card/80 backdrop-blur-sm border border-border/60 opacity-0 group-hover:opacity-100"
        aria-label="Copy file content"
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

      {/* Highlighted code with CSS-counter line numbers */}
      <div className="code-viewer overflow-x-auto text-sm [&_pre]:!m-0 [&_pre]:!rounded-none [&_pre]:!border-0 [&_pre]:py-3 [&_pre]:!bg-transparent [&_code]:!bg-transparent">
        {html ? (
          <div dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          // Plain-text fallback while Shiki loads
          <pre className="py-3">
            <code>
              {code.split("\n").map((line, i) => (
                <span key={i} className="line">
                  {line}
                  {"\n"}
                </span>
              ))}
            </code>
          </pre>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PreviewPanel
// ---------------------------------------------------------------------------

interface PreviewPanelProps {
  projectId: string;
}

export default function PreviewPanel({ projectId }: PreviewPanelProps) {
  const {
    selectedFile,
    fileContent,
    loadingFile,
    editMode,
    editorContent,
    dirty,
    saving,
    error,
    setEditMode,
    setEditorContent,
    saveFile,
    discardChanges,
    clearFileSelection,
  } = useFilesStore();

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Keyboard shortcut: Ctrl+S / Cmd+S to save
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (dirty && !saving) {
          void saveFile(projectId);
        }
      }
    },
    [dirty, saving, projectId, saveFile],
  );

  // Auto-focus textarea when entering edit mode
  useEffect(() => {
    if (editMode && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [editMode]);

  // Toast on successful save
  const prevSaving = useRef(saving);
  useEffect(() => {
    if (prevSaving.current && !saving && !error && editMode) {
      toast.success("File saved");
    }
    prevSaving.current = saving;
  }, [saving, error, editMode]);

  // -- Empty state ----------------------------------------------------------

  if (!selectedFile) {
    return (
      <div className="flex-1 flex items-center justify-center bg-background">
        <div className="text-center space-y-2">
          <File className="h-12 w-12 text-muted-foreground/30 mx-auto" />
          <p className="text-muted-foreground text-sm">Select a file to preview</p>
        </div>
      </div>
    );
  }

  // -- Derived values -------------------------------------------------------

  const fileName = selectedFile.split("/").pop() ?? selectedFile;
  const downloadUrl = getDownloadUrl(projectId, selectedFile);

  const handleDownload = () => {
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = fileName;
    a.click();
  };

  const canEdit = fileContent && isTextFile(fileName);

  // -- Content renderer -----------------------------------------------------

  const renderContent = () => {
    if (loadingFile) {
      return (
        <div className="flex-1 p-6 space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-4/6" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      );
    }

    // Image preview -- check before error so binary detection does not block images
    if (isImageFile(fileName)) {
      return (
        <div className="flex-1 flex items-center justify-center p-6 bg-muted/20">
          <img
            src={downloadUrl}
            alt={fileName}
            className="max-w-full max-h-full object-contain rounded-lg shadow"
          />
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center space-y-2">
            <AlertCircle className="h-8 w-8 text-destructive mx-auto" />
            <p className="text-sm text-destructive">{error}</p>
          </div>
        </div>
      );
    }

    // Edit mode
    if (editMode && fileContent) {
      return (
        <div className="flex-1 flex flex-col min-h-0">
          <textarea
            ref={textareaRef}
            value={editorContent}
            onChange={(e) => setEditorContent(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 w-full resize-none bg-background font-mono text-sm p-4 text-foreground outline-none border-0 focus:ring-0"
            style={{
              fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
            }}
            spellCheck={false}
          />
        </div>
      );
    }

    // Text preview with syntax highlighting
    if (fileContent && isTextFile(fileName)) {
      return (
        <ScrollArea className="flex-1">
          <div>
            {fileContent.truncated && (
              <div className="mx-4 mt-3 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-600 dark:text-amber-400">
                File is truncated -- showing partial content. Download for full file.
              </div>
            )}
            <CodeViewer code={fileContent.content} fileName={fileName} />
          </div>
        </ScrollArea>
      );
    }

    // Non-previewable (binary)
    if (fileContent || !loadingFile) {
      return (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center space-y-3">
            <File className="h-12 w-12 text-muted-foreground/30 mx-auto" />
            <p className="text-sm text-muted-foreground">Binary or unsupported file type</p>
            <Button variant="outline" size="sm" className="rounded-xl" onClick={handleDownload}>
              <Download className="h-4 w-4 mr-2" />
              Download file
            </Button>
          </div>
        </div>
      );
    }

    return null;
  };

  // -- Render ---------------------------------------------------------------

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-background">
      {/* File header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-card shrink-0">
        {/* Mobile back button */}
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 md:hidden rounded-lg text-muted-foreground hover:text-foreground"
          onClick={clearFileSelection}
          title="Back to file tree"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{selectedFile}</p>
          {fileContent && (
            <p className="text-xs text-muted-foreground mt-0.5">
              {formatBytes(fileContent.size)}
              {fileContent.modified && <> &middot; {formatDate(fileContent.modified)}</>}
              {fileContent.truncated && (
                <>
                  {" "}
                  &middot; <span className="text-amber-500">truncated</span>
                </>
              )}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 shrink-0">
          {editMode ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 rounded-lg text-muted-foreground hover:text-foreground"
                onClick={discardChanges}
                disabled={saving}
                title="Discard changes"
              >
                <X className="h-4 w-4 mr-1" />
                <span className="hidden sm:inline">Discard</span>
              </Button>
              <Button
                size="sm"
                className="h-8 rounded-lg"
                onClick={() => void saveFile(projectId)}
                disabled={!dirty || saving}
              >
                <Save className="h-4 w-4 mr-1" />
                {saving ? "Saving..." : "Save"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 rounded-lg"
                onClick={() => setEditMode(false)}
                disabled={saving}
              >
                <Eye className="h-4 w-4 mr-1" />
                <span className="hidden sm:inline">Preview</span>
              </Button>
            </>
          ) : (
            <>
              {canEdit && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-lg"
                  onClick={() => setEditMode(true)}
                >
                  <Edit3 className="h-4 w-4 mr-1" />
                  <span className="hidden sm:inline">Edit</span>
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="h-8 rounded-lg"
                onClick={handleDownload}
              >
                <Download className="h-4 w-4 mr-1" />
                <span className="hidden sm:inline">Download</span>
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Dirty indicator */}
      {dirty && (
        <div className="px-4 py-1.5 bg-amber-500/10 border-b border-amber-500/20 shrink-0">
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Unsaved changes &middot; Ctrl+S to save
          </p>
        </div>
      )}

      {/* Content area */}
      {renderContent()}
    </div>
  );
}
