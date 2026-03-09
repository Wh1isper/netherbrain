/**
 * Files page -- project file browser with tree + preview + terminal panels.
 *
 * Layout (desktop):
 *   +-----------------------------+
 *   | Header (back, title, term)  |
 *   +--------+--------------------+
 *   | Tree   | Preview            |
 *   | 280px  | flex               |
 *   +--------+--------------------+
 *   | ====== drag handle ======== |
 *   | Terminal (collapsible)      |
 *   +-----------------------------+
 *
 * Responsive (mobile):
 *   Tree full-width when no file selected;
 *   Preview full-width when file selected (back returns).
 *   Terminal: full-width bottom panel.
 *
 * Unsaved-changes guard via beforeunload.
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, FolderOpen, Menu, TerminalSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useFilesStore } from "@/stores/files";
import { useAppStore } from "@/stores/app";
import { useIsMobile } from "@/lib/hooks";
import FileTreePanel from "@/components/files/FileTreePanel";
import PreviewPanel from "@/components/files/PreviewPanel";
import TerminalPanel from "@/components/files/TerminalPanel";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TERMINAL_DEFAULT_HEIGHT = 250;
const TERMINAL_MIN_HEIGHT = 120;
const TERMINAL_MAX_RATIO = 0.6; // 60% of viewport

export default function Files() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const selectedFile = useFilesStore((s) => s.selectedFile);
  const dirty = useFilesStore((s) => s.dirty);
  const reset = useFilesStore((s) => s.reset);
  const isMobile = useIsMobile();
  const setMobileSidebarOpen = useAppStore((s) => s.setMobileSidebarOpen);

  // Terminal state
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalHeight, setTerminalHeight] = useState(TERMINAL_DEFAULT_HEIGHT);
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  // Reset store when project changes or unmounts
  useEffect(() => {
    return () => {
      reset();
    };
  }, [projectId, reset]);

  // Unsaved changes: warn before browser close / refresh
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // Keyboard shortcut: Ctrl+` to toggle terminal
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        setTerminalOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Drag-to-resize handler for the terminal panel
  const handleDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      draggingRef.current = true;
      const startY = e.clientY;
      const startHeight = terminalHeight;

      const onMove = (moveEvent: MouseEvent) => {
        if (!draggingRef.current) return;
        const maxHeight = window.innerHeight * TERMINAL_MAX_RATIO;
        const delta = startY - moveEvent.clientY;
        const newHeight = Math.min(maxHeight, Math.max(TERMINAL_MIN_HEIGHT, startHeight + delta));
        setTerminalHeight(newHeight);
      };

      const onUp = () => {
        draggingRef.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.body.style.cursor = "row-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [terminalHeight],
  );

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground">No project specified.</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-card shrink-0">
        {isMobile && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-xl text-muted-foreground hover:text-foreground"
            onClick={() => setMobileSidebarOpen(true)}
          >
            <Menu className="h-4 w-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-xl text-muted-foreground hover:text-foreground"
          onClick={() => {
            if (dirty && !window.confirm("You have unsaved changes. Leave?")) {
              return;
            }
            navigate(-1);
          }}
          title="Back"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <FolderOpen className="h-4 w-4 text-amber-500 shrink-0" />
          <h1 className="text-sm font-semibold text-foreground truncate">{projectId}</h1>
        </div>
        <Button
          variant={terminalOpen ? "secondary" : "ghost"}
          size="sm"
          className="h-8 rounded-xl text-xs gap-1.5"
          onClick={() => setTerminalOpen((prev) => !prev)}
          title="Toggle terminal (Ctrl+`)"
        >
          <TerminalSquare className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Terminal</span>
        </Button>
      </div>

      {/* Main content area: tree + preview + terminal */}
      <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
        {/* Top: file tree + preview (horizontal split) */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/*
           * Tree panel:
           *   Desktop -- always visible, fixed 280px.
           *   Mobile  -- full-width when no file selected; hidden when file selected.
           */}
          <div
            className={[
              "flex flex-col h-full border-r border-border",
              "w-full md:w-[280px] md:shrink-0",
              selectedFile ? "hidden md:flex" : "flex",
            ].join(" ")}
          >
            <FileTreePanel projectId={projectId} />
          </div>

          {/*
           * Preview panel:
           *   Desktop -- always visible, fills remaining space.
           *   Mobile  -- full-width when file selected; hidden otherwise.
           */}
          <div
            className={[
              "flex-1 flex flex-col min-h-0",
              selectedFile ? "flex" : "hidden md:flex",
            ].join(" ")}
          >
            <PreviewPanel projectId={projectId} />
          </div>
        </div>

        {/* Bottom: terminal panel (collapsible) */}
        {terminalOpen && (
          <>
            {/* Drag handle */}
            <div
              className="shrink-0 h-1.5 cursor-row-resize bg-border hover:bg-primary/30 transition-colors"
              onMouseDown={handleDragStart}
              title="Drag to resize terminal"
            />
            {/* Terminal */}
            <div className="shrink-0 overflow-hidden" style={{ height: terminalHeight }}>
              <TerminalPanel projectId={projectId} visible={terminalOpen} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
