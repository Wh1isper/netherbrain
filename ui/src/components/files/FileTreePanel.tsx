/**
 * FileTreePanel -- sidebar file explorer with drag-and-drop upload,
 * multi-select, batch operations, and create new file/directory.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import {
  ChevronRight,
  CheckSquare,
  Download,
  File,
  FilePlus,
  Folder,
  FolderOpen,
  FolderPlus,
  RefreshCw,
  Square,
  SquareCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilesStore } from "@/stores/files";
import { uploadFiles } from "@/api/files";
import type { FileEntry } from "@/api/types";

// ---------------------------------------------------------------------------
// FileTreeItem -- recursive row
// ---------------------------------------------------------------------------

interface FileTreeItemProps {
  entry: FileEntry;
  depth: number;
  projectId: string;
  selectedFile: string | null;
  selectMode: boolean;
  selectedPaths: Set<string>;
}

function FileTreeItem({
  entry,
  depth,
  projectId,
  selectedFile,
  selectMode,
  selectedPaths,
}: FileTreeItemProps) {
  const { treeData, expandedDirs, loadingDirs, toggleDir, selectFile, togglePathSelection } =
    useFilesStore();

  const isExpanded = expandedDirs.has(entry.path);
  const isLoading = loadingDirs.has(entry.path);
  const children = treeData[entry.path];
  const isSelected = selectedFile === entry.path;
  const isChecked = selectedPaths.has(entry.path);

  const handleClick = () => {
    if (selectMode) {
      togglePathSelection(entry.path);
      return;
    }
    if (entry.type === "directory") {
      void toggleDir(projectId, entry.path);
    } else {
      void selectFile(projectId, entry.path);
    }
  };

  return (
    <div>
      <button
        onClick={handleClick}
        className={[
          "w-full flex items-center gap-1.5 px-2 py-1 text-sm rounded-lg transition-colors text-left",
          "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
          isSelected && !selectMode
            ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
            : isChecked
              ? "bg-primary/10 text-sidebar-accent-foreground"
              : "text-muted-foreground",
        ].join(" ")}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        {selectMode ? (
          isChecked ? (
            <SquareCheck className="h-4 w-4 shrink-0 text-primary" />
          ) : (
            <Square className="h-4 w-4 shrink-0 text-muted-foreground/50" />
          )
        ) : entry.type === "directory" ? (
          <>
            <ChevronRight
              className={[
                "h-3.5 w-3.5 shrink-0 transition-transform duration-200",
                isExpanded ? "rotate-90" : "",
              ].join(" ")}
            />
            {isExpanded ? (
              <FolderOpen className="h-4 w-4 shrink-0 text-amber-500" />
            ) : (
              <Folder className="h-4 w-4 shrink-0 text-amber-500" />
            )}
          </>
        ) : (
          <>
            <span className="w-3.5 shrink-0" />
            <File className="h-4 w-4 shrink-0 text-muted-foreground/70" />
          </>
        )}
        <span className="truncate">{entry.name}</span>
      </button>

      {/* Children */}
      {entry.type === "directory" && isExpanded && !selectMode && (
        <div>
          {isLoading ? (
            <div style={{ paddingLeft: `${8 + (depth + 1) * 16}px` }} className="py-1 space-y-1">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-5 w-1/2" />
            </div>
          ) : children && children.length === 0 ? (
            <p
              className="text-xs text-muted-foreground/50 py-1 italic"
              style={{ paddingLeft: `${8 + (depth + 1) * 16}px` }}
            >
              Empty folder
            </p>
          ) : (
            children?.map((child) => (
              <FileTreeItem
                key={child.path}
                entry={child}
                depth={depth + 1}
                projectId={projectId}
                selectedFile={selectedFile}
                selectMode={selectMode}
                selectedPaths={selectedPaths}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create new dialog (inline input)
// ---------------------------------------------------------------------------

function InlineCreateInput({
  type,
  onSubmit,
  onCancel,
}: {
  type: "file" | "directory";
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (trimmed) onSubmit(trimmed);
    else onCancel();
  };

  return (
    <div className="flex items-center gap-1.5 px-2 py-1">
      {type === "directory" ? (
        <FolderPlus className="h-4 w-4 shrink-0 text-amber-500" />
      ) : (
        <FilePlus className="h-4 w-4 shrink-0 text-muted-foreground/70" />
      )}
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") handleSubmit();
          if (e.key === "Escape") onCancel();
        }}
        onBlur={handleSubmit}
        placeholder={type === "directory" ? "folder name" : "file name"}
        className="h-6 text-xs rounded px-1.5"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// FileTreePanel
// ---------------------------------------------------------------------------

interface FileTreePanelProps {
  projectId: string;
}

export default function FileTreePanel({ projectId }: FileTreePanelProps) {
  const {
    treeData,
    loadingDirs,
    selectedFile,
    selectMode,
    selectedPaths,
    loadDirectory,
    refreshDir,
    toggleSelectMode,
    selectAllInDir,
    clearSelection,
    deleteSelected,
    downloadSelected,
    createNewFile,
    createNewDir,
  } = useFilesStore();

  const uploadRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [creating, setCreating] = useState<"file" | "directory" | null>(null);

  const rootEntries = treeData[""] ?? null;
  const isRootLoading = loadingDirs.has("");

  // Initial load
  useEffect(() => {
    if (!treeData[""]) {
      void loadDirectory(projectId, "");
    }
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Determine upload target directory
  const getUploadDir = (): string => {
    if (!selectedFile) return "";
    const lastSlash = selectedFile.lastIndexOf("/");
    return lastSlash === -1 ? "" : selectedFile.slice(0, lastSlash);
  };

  const doUpload = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;
      const dir = getUploadDir();
      try {
        const result = await uploadFiles(projectId, dir, files);
        toast.success(`Uploaded ${result.uploaded.length} file(s)`);
        await refreshDir(projectId, dir);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error(`Upload failed: ${msg}`);
      }
    },
    [projectId, refreshDir], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    void doUpload(files);
    if (uploadRef.current) uploadRef.current.value = "";
  };

  const handleCreateSubmit = useCallback(
    async (name: string) => {
      if (!creating) return;
      const parentDir = selectedFile
        ? (() => {
            const idx = selectedFile.lastIndexOf("/");
            return idx === -1 ? "" : selectedFile.slice(0, idx);
          })()
        : "";
      const fullPath = parentDir ? `${parentDir}/${name}` : name;

      if (creating === "directory") {
        await createNewDir(projectId, fullPath);
      } else {
        await createNewFile(projectId, fullPath);
      }
      setCreating(null);
    },
    [creating, selectedFile, projectId, createNewDir, createNewFile],
  );

  const handleDeleteSelected = useCallback(async () => {
    if (selectedPaths.size === 0) return;
    const ok = window.confirm(`Delete ${selectedPaths.size} item(s)? This cannot be undone.`);
    if (!ok) return;
    await deleteSelected(projectId);
    toast.success("Deleted successfully");
  }, [selectedPaths.size, deleteSelected, projectId]);

  const handleDownloadSelected = useCallback(async () => {
    await downloadSelected(projectId);
  }, [downloadSelected, projectId]);

  // -- Drag and drop --------------------------------------------------------

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      void doUpload(files);
    },
    [doUpload],
  );

  return (
    <div
      className={[
        "flex flex-col h-full bg-sidebar transition-colors",
        dragOver ? "bg-primary/5" : "",
      ].join(" ")}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Toolbar */}
      <div className="flex items-center gap-0.5 px-2 py-2 border-b border-sidebar-border shrink-0">
        <span className="flex-1 text-xs font-medium text-muted-foreground uppercase tracking-wider px-1">
          Explorer
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          onClick={() => setCreating("file")}
          title="New file"
        >
          <FilePlus className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          onClick={() => setCreating("directory")}
          title="New folder"
        >
          <FolderPlus className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant={selectMode ? "secondary" : "ghost"}
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          onClick={toggleSelectMode}
          title={selectMode ? "Exit select mode" : "Select files"}
        >
          <CheckSquare className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          onClick={() => void refreshDir(projectId, "")}
          title="Refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
          onClick={() => uploadRef.current?.click()}
          title="Upload files"
        >
          <Upload className="h-3.5 w-3.5" />
        </Button>
        <input ref={uploadRef} type="file" multiple className="hidden" onChange={handleFileInput} />
      </div>

      {/* Multi-select action bar */}
      {selectMode && (
        <div className="flex items-center gap-1 px-2 py-1.5 border-b border-sidebar-border bg-sidebar-accent/50 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs px-2"
            onClick={() => selectAllInDir("")}
          >
            Select all
          </Button>
          {selectedPaths.size > 0 && (
            <>
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                {selectedPaths.size}
              </Badge>
              <div className="flex-1" />
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-foreground"
                onClick={() => void handleDownloadSelected()}
                title="Download selected"
              >
                <Download className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-destructive hover:text-destructive"
                onClick={() => void handleDeleteSelected()}
                title="Delete selected"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
          <div className="flex-1" />
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground"
            onClick={() => {
              clearSelection();
              toggleSelectMode();
            }}
            title="Cancel"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {/* Drag overlay hint */}
      {dragOver && (
        <div className="px-3 py-2 text-xs text-primary font-medium border-b border-primary/20 bg-primary/5 shrink-0">
          Drop files to upload
        </div>
      )}

      {/* Inline create input */}
      {creating && (
        <InlineCreateInput
          type={creating}
          onSubmit={(name) => void handleCreateSubmit(name)}
          onCancel={() => setCreating(null)}
        />
      )}

      {/* Tree */}
      <ScrollArea className="flex-1">
        <div className="py-1">
          {isRootLoading && !rootEntries ? (
            <div className="px-4 py-2 space-y-2">
              <Skeleton className="h-5 w-4/5" />
              <Skeleton className="h-5 w-3/5" />
              <Skeleton className="h-5 w-4/5" />
            </div>
          ) : rootEntries === null ? (
            <p className="px-4 py-6 text-xs text-muted-foreground text-center">
              Failed to load files.
            </p>
          ) : rootEntries.length === 0 ? (
            <p className="px-4 py-6 text-xs text-muted-foreground text-center">
              {dragOver ? "Drop files here" : "No files in this project."}
            </p>
          ) : (
            rootEntries.map((entry) => (
              <FileTreeItem
                key={entry.path}
                entry={entry}
                depth={0}
                projectId={projectId}
                selectedFile={selectedFile}
                selectMode={selectMode}
                selectedPaths={selectedPaths}
              />
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
