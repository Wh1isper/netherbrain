import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Plus, Star, Trash2, Copy, Folder, X } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { listPresets, createPreset, updatePreset, deletePreset, listToolsets } from "@/api/presets";
import {
  listWorkspaces,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
} from "@/api/workspaces";
import type { PresetResponse, WorkspaceResponse, ToolsetInfo } from "@/api/types";

// ============================================================================
// Shared utilities
// ============================================================================

function DeleteConfirmDialog({
  open,
  name,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  name: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete "{name}"?</DialogTitle>
          <DialogDescription>This action cannot be undone.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mx-6 mt-4 text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2 shrink-0">
      {message}
    </div>
  );
}

// ============================================================================
// Preset tab
// ============================================================================

interface PresetDraft {
  name: string;
  description: string;
  is_default: boolean;
  model_name: string;
  temperature: string;
  max_tokens: string;
  system_prompt: string;
  toolsets: Record<string, boolean>;
  subagents_include_builtin: boolean;
  subagents_async_enabled: boolean;
}

function presetToDraft(p: PresetResponse): PresetDraft {
  const toolsetMap: Record<string, boolean> = {};
  for (const ts of p.toolsets) {
    toolsetMap[ts.toolset_name] = ts.enabled !== false;
  }
  return {
    name: p.name,
    description: p.description ?? "",
    is_default: p.is_default,
    model_name: p.model.name,
    temperature: p.model.temperature != null ? String(p.model.temperature) : "",
    max_tokens: p.model.max_tokens != null ? String(p.model.max_tokens) : "",
    system_prompt: p.system_prompt,
    toolsets: toolsetMap,
    subagents_include_builtin: p.subagents?.include_builtin ?? false,
    subagents_async_enabled: p.subagents?.async_enabled ?? false,
  };
}

function emptyPresetDraft(cloneSource?: PresetResponse): PresetDraft {
  if (cloneSource) {
    const base = presetToDraft(cloneSource);
    return { ...base, name: `Copy of ${base.name}`, is_default: false };
  }
  return {
    name: "",
    description: "",
    is_default: false,
    model_name: "",
    temperature: "",
    max_tokens: "",
    system_prompt: "",
    toolsets: {},
    subagents_include_builtin: false,
    subagents_async_enabled: false,
  };
}

function PresetEditor({
  preset,
  cloneSource,
  availableToolsets,
  onSave,
  onDelete,
  onClone,
  saving,
}: {
  preset: PresetResponse | null;
  cloneSource?: PresetResponse;
  availableToolsets: ToolsetInfo[];
  onSave: (draft: PresetDraft) => Promise<void>;
  onDelete: () => void;
  onClone: () => void;
  saving: boolean;
}) {
  const isNew = preset === null;
  const stateKey = preset?.preset_id ?? (cloneSource ? `clone-${cloneSource.preset_id}` : "new");

  const [draft, setDraft] = useState<PresetDraft>(() =>
    preset ? presetToDraft(preset) : emptyPresetDraft(cloneSource),
  );
  const [deleteOpen, setDeleteOpen] = useState(false);

  // Reset draft whenever the target preset changes
  useEffect(() => {
    setDraft(preset ? presetToDraft(preset) : emptyPresetDraft(cloneSource));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateKey]);

  const set = <K extends keyof PresetDraft>(key: K, value: PresetDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const toggleToolset = (name: string) =>
    setDraft((d) => ({
      ...d,
      toolsets: { ...d.toolsets, [name]: !d.toolsets[name] },
    }));

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-border shrink-0">
        <span className="flex-1 text-sm font-medium text-foreground">
          {isNew ? (cloneSource ? `Clone: ${cloneSource.name}` : "New preset") : "Edit preset"}
        </span>
        {!isNew && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onClone}
            className="text-muted-foreground hover:text-foreground"
          >
            <Copy className="h-3.5 w-3.5 mr-1.5" />
            Clone
          </Button>
        )}
        {!isNew && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDeleteOpen(true)}
            className="text-destructive hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5 mr-1.5" />
            Delete
          </Button>
        )}
        <Button
          size="sm"
          onClick={() => void onSave(draft)}
          disabled={saving || !draft.name.trim() || !draft.model_name.trim()}
        >
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>

      {/* Form */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="px-6 py-5 space-y-6 max-w-2xl">
          {/* General */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              General
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="preset-name">Name</Label>
                <Input
                  id="preset-name"
                  value={draft.name}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="My preset"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="preset-desc">Description</Label>
                <Input
                  id="preset-desc"
                  value={draft.description}
                  onChange={(e) => set("description", e.target.value)}
                  placeholder="Optional"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input accent-primary"
                checked={draft.is_default}
                onChange={(e) => set("is_default", e.target.checked)}
              />
              <span className="text-sm">Set as default preset</span>
            </label>
          </section>

          <Separator />

          {/* Model */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Model
            </h3>
            <div className="space-y-1.5">
              <Label htmlFor="model-name">Model name</Label>
              <Input
                id="model-name"
                value={draft.model_name}
                onChange={(e) => set("model_name", e.target.value)}
                placeholder="e.g. claude-3-5-sonnet-20241022"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="temperature">Temperature</Label>
                <Input
                  id="temperature"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={draft.temperature}
                  onChange={(e) => set("temperature", e.target.value)}
                  placeholder="default"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="max-tokens">Max tokens</Label>
                <Input
                  id="max-tokens"
                  type="number"
                  min={1}
                  value={draft.max_tokens}
                  onChange={(e) => set("max_tokens", e.target.value)}
                  placeholder="default"
                />
              </div>
            </div>
          </section>

          <Separator />

          {/* System Prompt */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              System Prompt
            </h3>
            <Textarea
              value={draft.system_prompt}
              onChange={(e) => set("system_prompt", e.target.value)}
              placeholder="You are a helpful assistant..."
              className="font-mono text-xs min-h-36 resize-y"
              rows={8}
            />
          </section>

          <Separator />

          {/* Toolsets */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Toolsets
            </h3>
            {availableToolsets.length === 0 ? (
              <p className="text-sm text-muted-foreground">No toolsets available.</p>
            ) : (
              <div className="space-y-2.5">
                {availableToolsets.map((ts) => (
                  <label key={ts.name} className="flex items-start gap-3 cursor-pointer group">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 rounded border-input accent-primary shrink-0"
                      checked={draft.toolsets[ts.name] ?? false}
                      onChange={() => toggleToolset(ts.name)}
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium leading-none">{ts.name}</span>
                        {ts.is_alias && (
                          <Badge variant="secondary" className="text-[10px] px-1 py-0 h-4">
                            alias
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5 leading-snug">
                        {ts.description}
                      </p>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </section>

          <Separator />

          {/* Subagents */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Subagents
            </h3>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input accent-primary"
                checked={draft.subagents_include_builtin}
                onChange={(e) => set("subagents_include_builtin", e.target.checked)}
              />
              <span className="text-sm">Include built-in subagents</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input accent-primary"
                checked={draft.subagents_async_enabled}
                onChange={(e) => set("subagents_async_enabled", e.target.checked)}
              />
              <span className="text-sm">Enable async subagents</span>
            </label>
          </section>

          {/* Bottom padding */}
          <div className="h-4" />
        </div>
      </ScrollArea>

      {!isNew && preset && (
        <DeleteConfirmDialog
          open={deleteOpen}
          name={preset.name}
          onConfirm={() => {
            setDeleteOpen(false);
            onDelete();
          }}
          onCancel={() => setDeleteOpen(false)}
        />
      )}
    </div>
  );
}

function PresetsTab() {
  const [presets, setPresets] = useState<PresetResponse[]>([]);
  const [availableToolsets, setAvailableToolsets] = useState<ToolsetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"view" | "new" | "clone">("view");
  const [cloneSource, setCloneSource] = useState<PresetResponse | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedPreset = presets.find((p) => p.preset_id === selectedId) ?? null;
  const showEditor = mode !== "view" || selectedPreset !== null;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ps, ts] = await Promise.all([listPresets(), listToolsets()]);
      setPresets(ps);
      setAvailableToolsets(ts);
      if (ps.length > 0 && !selectedId) {
        setSelectedId(ps[0].preset_id);
        setMode("view");
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void load();
  }, [load]);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    setMode("view");
    setCloneSource(undefined);
  };

  const handleNew = () => {
    setSelectedId(null);
    setCloneSource(undefined);
    setMode("new");
  };

  const handleClone = () => {
    if (!selectedPreset) return;
    setCloneSource(selectedPreset);
    setSelectedId(null);
    setMode("clone");
  };

  const handleSave = async (draft: PresetDraft) => {
    setSaving(true);
    setError(null);
    try {
      const toolsets = availableToolsets
        .filter((ts) => draft.toolsets[ts.name])
        .map((ts) => ({ toolset_name: ts.name, enabled: true }));
      const model = {
        name: draft.model_name,
        temperature: draft.temperature !== "" ? parseFloat(draft.temperature) : null,
        max_tokens: draft.max_tokens !== "" ? parseInt(draft.max_tokens, 10) : null,
      };
      const subagents = {
        include_builtin: draft.subagents_include_builtin,
        async_enabled: draft.subagents_async_enabled,
      };

      if (mode === "view" && selectedPreset) {
        const updated = await updatePreset(selectedPreset.preset_id, {
          name: draft.name,
          description: draft.description || null,
          is_default: draft.is_default,
          model,
          system_prompt: draft.system_prompt,
          toolsets,
          subagents,
        });
        setPresets((ps) => ps.map((p) => (p.preset_id === updated.preset_id ? updated : p)));
        setSelectedId(updated.preset_id);
      } else {
        const created = await createPreset({
          name: draft.name,
          description: draft.description || null,
          is_default: draft.is_default,
          model,
          system_prompt: draft.system_prompt,
          toolsets,
          subagents,
        });
        setPresets((ps) => [...ps, created]);
        setSelectedId(created.preset_id);
        setMode("view");
        setCloneSource(undefined);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedPreset) return;
    setError(null);
    try {
      await deletePreset(selectedPreset.preset_id);
      const remaining = presets.filter((p) => p.preset_id !== selectedPreset.preset_id);
      setPresets(remaining);
      if (remaining.length > 0) {
        setSelectedId(remaining[0].preset_id);
        setMode("view");
      } else {
        setSelectedId(null);
        setMode("new");
      }
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="flex h-full min-h-0">
      {/* List panel */}
      <div className="w-60 shrink-0 border-r border-border flex flex-col min-h-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <span className="text-sm font-semibold">Presets</span>
          <Button variant="ghost" size="sm" onClick={handleNew} className="h-7 text-xs gap-1">
            <Plus className="h-3.5 w-3.5" />
            New
          </Button>
        </div>
        <ScrollArea className="flex-1">
          {loading ? (
            <div className="p-3 space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full rounded-md" />
              ))}
            </div>
          ) : presets.length === 0 ? (
            <p className="px-4 py-6 text-xs text-muted-foreground text-center">No presets yet.</p>
          ) : (
            <div className="p-2 space-y-0.5">
              {presets.map((p) => (
                <button
                  key={p.preset_id}
                  onClick={() => handleSelect(p.preset_id)}
                  className={[
                    "w-full text-left px-3 py-2.5 rounded-md text-sm transition-colors",
                    "hover:bg-accent hover:text-accent-foreground",
                    selectedId === p.preset_id && mode === "view"
                      ? "bg-accent text-accent-foreground"
                      : "text-foreground",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    {p.is_default && (
                      <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-400" />
                    )}
                    <span className="flex-1 truncate font-medium text-sm">{p.name}</span>
                  </div>
                  <div className="mt-1">
                    <Badge
                      variant="secondary"
                      className="text-[10px] px-1.5 py-0 font-normal max-w-full truncate"
                    >
                      {p.model.name}
                    </Badge>
                  </div>
                </button>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>

      {/* Editor panel */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        {error && <ErrorBanner message={error} />}
        {showEditor ? (
          <PresetEditor
            preset={mode === "view" ? selectedPreset : null}
            cloneSource={mode === "clone" ? cloneSource : undefined}
            availableToolsets={availableToolsets}
            onSave={handleSave}
            onDelete={() => void handleDelete()}
            onClone={handleClone}
            saving={saving}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
            Select a preset to edit.
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Workspaces tab
// ============================================================================

interface WorkspaceDraft {
  name: string;
  projects: string[];
}

function workspaceToDraft(w: WorkspaceResponse): WorkspaceDraft {
  return { name: w.name ?? "", projects: [...w.projects] };
}

function emptyWorkspaceDraft(): WorkspaceDraft {
  return { name: "", projects: [] };
}

function WorkspaceEditor({
  workspace,
  onSave,
  onDelete,
  saving,
}: {
  workspace: WorkspaceResponse | null;
  onSave: (draft: WorkspaceDraft) => Promise<void>;
  onDelete: () => void;
  saving: boolean;
}) {
  const isNew = workspace === null;
  const isDefault =
    workspace?.metadata?.source === "webui" && workspace?.metadata?.default === true;

  const [draft, setDraft] = useState<WorkspaceDraft>(
    workspace ? workspaceToDraft(workspace) : emptyWorkspaceDraft(),
  );
  const [newProject, setNewProject] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    setDraft(workspace ? workspaceToDraft(workspace) : emptyWorkspaceDraft());
    setNewProject("");
  }, [workspace?.workspace_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const addProject = () => {
    const val = newProject.trim();
    if (!val || draft.projects.includes(val)) return;
    setDraft((d) => ({ ...d, projects: [...d.projects, val] }));
    setNewProject("");
  };

  const removeProject = (p: string) =>
    setDraft((d) => ({ ...d, projects: d.projects.filter((x) => x !== p) }));

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-border shrink-0">
        <span className="flex-1 text-sm font-medium text-foreground">
          {isNew ? "New workspace" : "Edit workspace"}
        </span>
        {!isNew && !isDefault && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDeleteOpen(true)}
            className="text-destructive hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5 mr-1.5" />
            Delete
          </Button>
        )}
        <Button
          size="sm"
          onClick={() => void onSave(draft)}
          disabled={saving || !draft.name.trim()}
        >
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>

      {/* Form */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="px-6 py-5 space-y-6 max-w-2xl">
          {/* General */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              General
            </h3>
            <div className="space-y-1.5">
              <Label htmlFor="ws-name">Name</Label>
              <Input
                id="ws-name"
                value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                placeholder="My workspace"
              />
            </div>
            {isDefault && (
              <p className="text-xs text-muted-foreground">
                This is the default workspace and cannot be deleted.
              </p>
            )}
          </section>

          <Separator />

          {/* Folders */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Folders
            </h3>
            {draft.projects.length === 0 ? (
              <p className="text-sm text-muted-foreground">No folders added.</p>
            ) : (
              <div className="space-y-1.5">
                {draft.projects.map((p) => (
                  <div
                    key={p}
                    className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm"
                  >
                    <Folder className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="flex-1 font-mono text-xs truncate">{p}</span>
                    <button
                      onClick={() => removeProject(p)}
                      className="text-muted-foreground hover:text-destructive transition-colors"
                      title="Remove folder"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <Input
                value={newProject}
                onChange={(e) => setNewProject(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addProject();
                  }
                }}
                placeholder="Add folder path..."
                className="flex-1 font-mono text-xs"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={addProject}
                disabled={!newProject.trim()}
              >
                Add
              </Button>
            </div>
          </section>

          <div className="h-4" />
        </div>
      </ScrollArea>

      {!isNew && workspace && (
        <DeleteConfirmDialog
          open={deleteOpen}
          name={workspace.name ?? workspace.workspace_id}
          onConfirm={() => {
            setDeleteOpen(false);
            onDelete();
          }}
          onCancel={() => setDeleteOpen(false)}
        />
      )}
    </div>
  );
}

function WorkspacesTab() {
  const [workspaces, setWorkspaces] = useState<WorkspaceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Show only UI-created workspaces
  const webuiWorkspaces = workspaces.filter((w) => w.metadata?.source === "webui");
  const selectedWorkspace = webuiWorkspaces.find((w) => w.workspace_id === selectedId) ?? null;
  const showEditor = isNew || selectedWorkspace !== null;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const ws = await listWorkspaces();
      setWorkspaces(ws);
      const webui = ws.filter((w) => w.metadata?.source === "webui");
      if (webui.length > 0 && !selectedId) {
        setSelectedId(webui[0].workspace_id);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async (draft: WorkspaceDraft) => {
    setSaving(true);
    setError(null);
    try {
      if (!isNew && selectedWorkspace) {
        const updated = await updateWorkspace(selectedWorkspace.workspace_id, {
          name: draft.name || null,
          projects: draft.projects,
          metadata: selectedWorkspace.metadata ?? undefined,
        });
        setWorkspaces((ws) =>
          ws.map((w) => (w.workspace_id === updated.workspace_id ? updated : w)),
        );
        setSelectedId(updated.workspace_id);
      } else {
        const created = await createWorkspace({
          name: draft.name || null,
          projects: draft.projects,
          metadata: { source: "webui" },
        });
        setWorkspaces((ws) => [...ws, created]);
        setSelectedId(created.workspace_id);
        setIsNew(false);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedWorkspace) return;
    setError(null);
    try {
      await deleteWorkspace(selectedWorkspace.workspace_id);
      const remaining = webuiWorkspaces.filter(
        (w) => w.workspace_id !== selectedWorkspace.workspace_id,
      );
      setWorkspaces((ws) => ws.filter((w) => w.workspace_id !== selectedWorkspace.workspace_id));
      if (remaining.length > 0) {
        setSelectedId(remaining[0].workspace_id);
        setIsNew(false);
      } else {
        setSelectedId(null);
        setIsNew(true);
      }
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="flex h-full min-h-0">
      {/* List panel */}
      <div className="w-60 shrink-0 border-r border-border flex flex-col min-h-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <span className="text-sm font-semibold">Workspaces</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setIsNew(true);
              setSelectedId(null);
            }}
            className="h-7 text-xs gap-1"
          >
            <Plus className="h-3.5 w-3.5" />
            New
          </Button>
        </div>
        <ScrollArea className="flex-1">
          {loading ? (
            <div className="p-3 space-y-2">
              {[1, 2].map((i) => (
                <Skeleton key={i} className="h-12 w-full rounded-md" />
              ))}
            </div>
          ) : webuiWorkspaces.length === 0 ? (
            <p className="px-4 py-6 text-xs text-muted-foreground text-center">
              No workspaces yet.
            </p>
          ) : (
            <div className="p-2 space-y-0.5">
              {webuiWorkspaces.map((w) => {
                const isDefault = w.metadata?.source === "webui" && w.metadata?.default === true;
                return (
                  <button
                    key={w.workspace_id}
                    onClick={() => {
                      setSelectedId(w.workspace_id);
                      setIsNew(false);
                    }}
                    className={[
                      "w-full text-left px-3 py-2.5 rounded-md text-sm transition-colors",
                      "hover:bg-accent hover:text-accent-foreground",
                      selectedId === w.workspace_id && !isNew
                        ? "bg-accent text-accent-foreground"
                        : "text-foreground",
                    ].join(" ")}
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="flex-1 truncate font-medium">
                        {w.name ?? w.workspace_id}
                      </span>
                      {isDefault && (
                        <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">
                          default
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {w.projects.length} folder
                      {w.projects.length !== 1 ? "s" : ""}
                    </p>
                  </button>
                );
              })}
            </div>
          )}
        </ScrollArea>
      </div>

      {/* Editor panel */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        {error && <ErrorBanner message={error} />}
        {showEditor ? (
          <WorkspaceEditor
            workspace={isNew ? null : selectedWorkspace}
            onSave={handleSave}
            onDelete={() => void handleDelete()}
            saving={saving}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
            Select a workspace to edit.
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Main Settings page
// ============================================================================

export default function Settings() {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border shrink-0">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground"
          onClick={() => navigate("/")}
          title="Back to chat"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-base font-semibold">Settings</h1>
      </div>

      {/* Tabs fill remaining height */}
      <Tabs defaultValue="presets" className="flex-1 flex flex-col min-h-0 px-6 pt-4 gap-0">
        <TabsList className="self-start shrink-0">
          <TabsTrigger value="presets">Presets</TabsTrigger>
          <TabsTrigger value="workspaces">Workspaces</TabsTrigger>
        </TabsList>
        <TabsContent value="presets" className="flex-1 min-h-0 mt-3">
          <PresetsTab />
        </TabsContent>
        <TabsContent value="workspaces" className="flex-1 min-h-0 mt-3">
          <WorkspacesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
