/**
 * Files page -- project file browser with tree + preview panels.
 *
 * Responsive layout:
 *   Desktop (md+): side-by-side tree (280px) + preview (flex).
 *   Mobile  (<md): tree full-width when no file selected,
 *                  preview full-width when file selected (back button returns).
 *
 * Unsaved-changes guard via beforeunload.
 */

import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useFilesStore } from "@/stores/files";
import FileTreePanel from "@/components/files/FileTreePanel";
import PreviewPanel from "@/components/files/PreviewPanel";

export default function Files() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const selectedFile = useFilesStore((s) => s.selectedFile);
  const dirty = useFilesStore((s) => s.dirty);
  const reset = useFilesStore((s) => s.reset);

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

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground">No project specified.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-card shrink-0">
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
        <div className="flex items-center gap-2">
          <FolderOpen className="h-4 w-4 text-amber-500" />
          <h1 className="text-sm font-semibold text-foreground">{projectId}</h1>
        </div>
      </div>

      {/* Main content: responsive tree + preview */}
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
    </div>
  );
}
