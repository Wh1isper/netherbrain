/**
 * Zustand store for the Files page browser state.
 * NOT persisted -- ephemeral UI state that resets on unmount / project change.
 */

import { create } from "zustand";
import type { FileEntry, FileReadResponse } from "../api/types";
import { listFiles, readFile, writeFile } from "../api/files";
import { shouldReadContent } from "../components/files/file-utils";

interface FilesState {
  // Tree
  treeData: Record<string, FileEntry[]>; // path -> entries cache
  expandedDirs: Set<string>;
  loadingDirs: Set<string>;

  // Selection
  selectedFile: string | null; // relative path

  // File content
  fileContent: FileReadResponse | null;
  loadingFile: boolean;

  // Editor
  editMode: boolean;
  editorContent: string; // draft content in edit mode
  dirty: boolean; // unsaved changes
  saving: boolean;

  // Error state
  error: string | null;

  // Actions
  loadDirectory: (projectId: string, path: string) => Promise<void>;
  toggleDir: (projectId: string, path: string) => Promise<void>;
  selectFile: (projectId: string, path: string) => Promise<void>;
  refreshDir: (projectId: string, path: string) => Promise<void>;
  setEditMode: (on: boolean) => void;
  setEditorContent: (content: string) => void;
  saveFile: (projectId: string) => Promise<void>;
  discardChanges: () => void;
  clearSelection: () => void;
  reset: () => void;
}

const initialState = {
  treeData: {} as Record<string, FileEntry[]>,
  expandedDirs: new Set<string>(),
  loadingDirs: new Set<string>(),
  selectedFile: null as string | null,
  fileContent: null as FileReadResponse | null,
  loadingFile: false,
  editMode: false,
  editorContent: "",
  dirty: false,
  saving: false,
  error: null as string | null,
};

export const useFilesStore = create<FilesState>()((set, get) => ({
  ...initialState,

  loadDirectory: async (projectId, path) => {
    const state = get();
    if (state.loadingDirs.has(path)) return;

    set((s) => ({
      loadingDirs: new Set([...s.loadingDirs, path]),
      error: null,
    }));

    try {
      const res = await listFiles(projectId, path);
      // Backend already returns entries sorted (dirs first, alpha).
      set((s) => ({
        treeData: { ...s.treeData, [path]: res.entries },
        loadingDirs: new Set([...s.loadingDirs].filter((p) => p !== path)),
      }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      set((s) => ({
        error: msg,
        loadingDirs: new Set([...s.loadingDirs].filter((p) => p !== path)),
      }));
    }
  },

  toggleDir: async (projectId, path) => {
    const state = get();
    const isExpanded = state.expandedDirs.has(path);

    if (isExpanded) {
      set((s) => {
        const next = new Set(s.expandedDirs);
        next.delete(path);
        return { expandedDirs: next };
      });
    } else {
      set((s) => {
        const next = new Set(s.expandedDirs);
        next.add(path);
        return { expandedDirs: next };
      });
      if (!state.treeData[path]) {
        await get().loadDirectory(projectId, path);
      }
    }
  },

  selectFile: async (projectId, path) => {
    // Warn if unsaved changes
    const { dirty } = get();
    if (dirty) {
      const ok = window.confirm("You have unsaved changes. Discard and switch file?");
      if (!ok) return;
    }

    set({
      selectedFile: path,
      fileContent: null,
      loadingFile: true,
      editMode: false,
      editorContent: "",
      dirty: false,
      error: null,
    });

    // Only fetch content for text files; images and binary files
    // are handled via download URL or shown as non-previewable.
    if (!shouldReadContent(path)) {
      set({ loadingFile: false });
      return;
    }

    try {
      const content = await readFile(projectId, path);
      set({ fileContent: content, loadingFile: false });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      set({ error: msg, loadingFile: false });
    }
  },

  refreshDir: async (projectId, path) => {
    set((s) => {
      const next = { ...s.treeData };
      delete next[path];
      return { treeData: next };
    });
    await get().loadDirectory(projectId, path);
  },

  setEditMode: (on) => {
    const { fileContent } = get();
    if (on) {
      set({
        editMode: true,
        editorContent: fileContent?.content ?? "",
        dirty: false,
      });
    } else {
      set({ editMode: false, dirty: false });
    }
  },

  setEditorContent: (content) => {
    const { fileContent } = get();
    set({
      editorContent: content,
      dirty: content !== (fileContent?.content ?? ""),
    });
  },

  saveFile: async (projectId) => {
    const { selectedFile, editorContent } = get();
    if (!selectedFile) return;

    set({ saving: true, error: null });
    try {
      await writeFile(projectId, selectedFile, editorContent);
      const updated = await readFile(projectId, selectedFile);
      set({
        fileContent: updated,
        editorContent: updated.content,
        dirty: false,
        saving: false,
        editMode: true,
      });
      // Refresh parent directory to update metadata
      const parentPath = selectedFile.includes("/")
        ? selectedFile.substring(0, selectedFile.lastIndexOf("/"))
        : "";
      const { treeData } = get();
      if (treeData[parentPath]) {
        void get().refreshDir(projectId, parentPath);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      set({ error: msg, saving: false });
    }
  },

  discardChanges: () => {
    const { fileContent } = get();
    set({
      editorContent: fileContent?.content ?? "",
      dirty: false,
    });
  },

  clearSelection: () => {
    const { dirty } = get();
    if (dirty) {
      const ok = window.confirm("You have unsaved changes. Discard?");
      if (!ok) return;
    }
    set({
      selectedFile: null,
      fileContent: null,
      editMode: false,
      editorContent: "",
      dirty: false,
      error: null,
    });
  },

  reset: () => {
    set({
      ...initialState,
      treeData: {},
      expandedDirs: new Set(),
      loadingDirs: new Set(),
    });
  },
}));
