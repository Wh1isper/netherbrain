import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Plus,
  Star,
  Trash2,
  Copy,
  Folder,
  X,
  Eye,
  EyeOff,
  KeyRound,
  UserX,
  RotateCcw,
  Shield,
  User,
} from "lucide-react";
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
import {
  listPresets,
  createPreset,
  updatePreset,
  deletePreset,
  listToolsets,
  listModelPresets,
} from "@/api/presets";
import { updateUser } from "@/api/users";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  listWorkspaces,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
} from "@/api/workspaces";
import { changePassword } from "@/api/auth";
import { listUsers, createUser, deactivateUser, resetPassword } from "@/api/users";
import { listKeys, createKey, revokeKey } from "@/api/keys";
import { useAppStore } from "@/stores/app";
import { ApiError } from "@/api/client";
import type {
  PresetResponse,
  WorkspaceResponse,
  ToolsetInfo,
  ModelPresetsResponse,
  UserResponse,
  ApiKeyResponse,
  ApiKeyCreateResponse,
  UserCreateResponse,
} from "@/api/types";

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

interface McpServerDraft {
  url: string;
  transport: "streamable_http" | "sse";
  headers: string;
  tool_prefix: string;
  timeout: string;
  description: string;
}

interface PresetDraft {
  name: string;
  description: string;
  is_default: boolean;
  // Model
  model_name: string;
  model_settings_preset: string;
  model_config_preset: string;
  temperature: string;
  max_tokens: string;
  // System prompt
  system_prompt: string;
  // Toolsets
  toolsets: Record<string, boolean>;
  // Subagents
  subagents_include_builtin: boolean;
  subagents_async_enabled: boolean;
  // Environment
  env_mode: "local" | "sandbox";
  env_container_id: string;
  env_container_workdir: string;
  // Tool config
  tool_skip_url_verification: boolean;
  tool_enable_load_document: boolean;
  tool_image_model: string;
  tool_video_model: string;
  // MCP servers
  mcp_servers: McpServerDraft[];
}

function presetToDraft(p: PresetResponse): PresetDraft {
  const toolsetMap: Record<string, boolean> = {};
  for (const ts of p.toolsets) {
    toolsetMap[ts.toolset_name] = ts.enabled !== false;
  }
  const ms = p.model.model_settings as Record<string, number | undefined> | null;
  return {
    name: p.name,
    description: p.description ?? "",
    is_default: p.is_default,
    model_name: p.model.name,
    model_settings_preset: p.model.model_settings_preset ?? "",
    model_config_preset: p.model.model_config_preset ?? "",
    temperature: ms?.temperature != null ? String(ms.temperature) : "",
    max_tokens: ms?.max_tokens != null ? String(ms.max_tokens) : "",
    system_prompt: p.system_prompt,
    toolsets: toolsetMap,
    subagents_include_builtin: p.subagents?.include_builtin ?? true,
    subagents_async_enabled: p.subagents?.async_enabled ?? false,
    env_mode: p.environment?.mode ?? "local",
    env_container_id: p.environment?.container_id ?? "",
    env_container_workdir: p.environment?.container_workdir ?? "/workspace",
    tool_skip_url_verification: p.tool_config?.skip_url_verification ?? true,
    tool_enable_load_document: p.tool_config?.enable_load_document ?? false,
    tool_image_model: p.tool_config?.image_understanding_model ?? "",
    tool_video_model: p.tool_config?.video_understanding_model ?? "",
    mcp_servers: (p.mcp_servers ?? []).map((s) => ({
      url: s.url,
      transport: s.transport ?? "streamable_http",
      headers: s.headers ? JSON.stringify(s.headers, null, 2) : "",
      tool_prefix: s.tool_prefix ?? "",
      timeout: s.timeout != null ? String(s.timeout) : "",
      description: s.description ?? "",
    })),
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
    model_settings_preset: "",
    model_config_preset: "",
    temperature: "",
    max_tokens: "",
    system_prompt: "",
    toolsets: {},
    subagents_include_builtin: true,
    subagents_async_enabled: false,
    env_mode: "local",
    env_container_id: "",
    env_container_workdir: "/workspace",
    tool_skip_url_verification: true,
    tool_enable_load_document: false,
    tool_image_model: "",
    tool_video_model: "",
    mcp_servers: [],
  };
}

function PresetEditor({
  preset,
  cloneSource,
  availableToolsets,
  modelPresets,
  onSave,
  onDelete,
  onClone,
  saving,
}: {
  preset: PresetResponse | null;
  cloneSource?: PresetResponse;
  availableToolsets: ToolsetInfo[];
  modelPresets: ModelPresetsResponse | null;
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
                placeholder="e.g. anthropic:claude-sonnet-4"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="settings-preset">Settings preset</Label>
                <Select
                  value={draft.model_settings_preset || "_none"}
                  onValueChange={(v) => set("model_settings_preset", v === "_none" ? "" : v)}
                >
                  <SelectTrigger id="settings-preset" className="text-sm">
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="_none">None</SelectItem>
                    {modelPresets?.model_settings_presets.map((p) => (
                      <SelectItem key={p.name} value={p.name}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="config-preset">Config preset</Label>
                <Select
                  value={draft.model_config_preset || "_none"}
                  onValueChange={(v) => set("model_config_preset", v === "_none" ? "" : v)}
                >
                  <SelectTrigger id="config-preset" className="text-sm">
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="_none">None</SelectItem>
                    {modelPresets?.model_config_presets.map((p) => (
                      <SelectItem key={p.name} value={p.name}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
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

          {/* Environment */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Environment
            </h3>
            <div className="space-y-1.5">
              <Label>Mode</Label>
              <Select
                value={draft.env_mode}
                onValueChange={(v) => set("env_mode", v as "local" | "sandbox")}
              >
                <SelectTrigger className="text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">Local</SelectItem>
                  <SelectItem value="sandbox">Sandbox</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {draft.env_mode === "sandbox" && (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="container-id">Container ID</Label>
                  <Input
                    id="container-id"
                    value={draft.env_container_id}
                    onChange={(e) => set("env_container_id", e.target.value)}
                    placeholder="Required for sandbox"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="container-workdir">Working directory</Label>
                  <Input
                    id="container-workdir"
                    value={draft.env_container_workdir}
                    onChange={(e) => set("env_container_workdir", e.target.value)}
                    placeholder="/workspace"
                  />
                </div>
              </div>
            )}
          </section>

          <Separator />

          {/* Tool Config */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Tool Config
            </h3>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input accent-primary"
                checked={draft.tool_skip_url_verification}
                onChange={(e) => set("tool_skip_url_verification", e.target.checked)}
              />
              <span className="text-sm">Skip URL verification</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input accent-primary"
                checked={draft.tool_enable_load_document}
                onChange={(e) => set("tool_enable_load_document", e.target.checked)}
              />
              <span className="text-sm">Enable document loading</span>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="img-model">Image understanding model</Label>
                <Input
                  id="img-model"
                  value={draft.tool_image_model}
                  onChange={(e) => set("tool_image_model", e.target.value)}
                  placeholder="default"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="vid-model">Video understanding model</Label>
                <Input
                  id="vid-model"
                  value={draft.tool_video_model}
                  onChange={(e) => set("tool_video_model", e.target.value)}
                  placeholder="default"
                />
              </div>
            </div>
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

          <Separator />

          {/* MCP Servers */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              MCP Servers
            </h3>
            {draft.mcp_servers.map((srv, idx) => (
              <div key={idx} className="rounded-md border border-border p-3 space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">
                    Server {idx + 1}
                  </span>
                  <button
                    onClick={() =>
                      setDraft((d) => ({
                        ...d,
                        mcp_servers: d.mcp_servers.filter((_, i) => i !== idx),
                      }))
                    }
                    className="text-muted-foreground hover:text-destructive transition-colors"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="col-span-2 space-y-1">
                    <Label className="text-xs">URL</Label>
                    <Input
                      value={srv.url}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          mcp_servers: d.mcp_servers.map((s, i) =>
                            i === idx ? { ...s, url: e.target.value } : s,
                          ),
                        }))
                      }
                      placeholder="http://localhost:8080/mcp"
                      className="text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Transport</Label>
                    <Select
                      value={srv.transport}
                      onValueChange={(v) =>
                        setDraft((d) => ({
                          ...d,
                          mcp_servers: d.mcp_servers.map((s, i) =>
                            i === idx ? { ...s, transport: v as "streamable_http" | "sse" } : s,
                          ),
                        }))
                      }
                    >
                      <SelectTrigger className="text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="streamable_http">Streamable HTTP</SelectItem>
                        <SelectItem value="sse">SSE</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Tool prefix</Label>
                    <Input
                      value={srv.tool_prefix}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          mcp_servers: d.mcp_servers.map((s, i) =>
                            i === idx ? { ...s, tool_prefix: e.target.value } : s,
                          ),
                        }))
                      }
                      placeholder="optional"
                      className="text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Timeout (s)</Label>
                    <Input
                      type="number"
                      min={0}
                      value={srv.timeout}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          mcp_servers: d.mcp_servers.map((s, i) =>
                            i === idx ? { ...s, timeout: e.target.value } : s,
                          ),
                        }))
                      }
                      placeholder="default"
                      className="text-xs"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Description</Label>
                  <Input
                    value={srv.description}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        mcp_servers: d.mcp_servers.map((s, i) =>
                          i === idx ? { ...s, description: e.target.value } : s,
                        ),
                      }))
                    }
                    placeholder="What this server provides (for tool search)"
                    className="text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Headers (JSON)</Label>
                  <Textarea
                    value={srv.headers}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        mcp_servers: d.mcp_servers.map((s, i) =>
                          i === idx ? { ...s, headers: e.target.value } : s,
                        ),
                      }))
                    }
                    placeholder='{"Authorization": "Bearer ..."}'
                    className="font-mono text-xs min-h-[60px] resize-y"
                    rows={2}
                  />
                </div>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setDraft((d) => ({
                  ...d,
                  mcp_servers: [
                    ...d.mcp_servers,
                    {
                      url: "",
                      transport: "streamable_http",
                      headers: "",
                      tool_prefix: "",
                      timeout: "",
                      description: "",
                    },
                  ],
                }))
              }
            >
              <Plus className="h-3.5 w-3.5 mr-1.5" />
              Add MCP Server
            </Button>
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
  const [modelPresets, setModelPresets] = useState<ModelPresetsResponse | null>(null);
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
      const [ps, ts, mp] = await Promise.all([listPresets(), listToolsets(), listModelPresets()]);
      setPresets(ps);
      setAvailableToolsets(ts);
      setModelPresets(mp);
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
      // When editing, preserve backend fields that the UI doesn't expose.
      const base = mode === "view" ? selectedPreset : null;

      // Merge toolsets: preserve exclude_tools from existing entries.
      const existingToolsets = base?.toolsets ?? [];
      const toolsets = availableToolsets
        .filter((ts) => draft.toolsets[ts.name])
        .map((ts) => {
          const existing = existingToolsets.find((e) => e.toolset_name === ts.name);
          return {
            toolset_name: ts.name,
            enabled: true,
            ...(existing?.exclude_tools?.length ? { exclude_tools: existing.exclude_tools } : {}),
          };
        });

      // Build model_settings dict from individual overrides.
      const modelSettingsOverrides: Record<string, unknown> = {};
      const tempVal = parseFloat(draft.temperature);
      if (draft.temperature !== "" && Number.isFinite(tempVal))
        modelSettingsOverrides.temperature = tempVal;
      const maxTokVal = parseInt(draft.max_tokens, 10);
      if (draft.max_tokens !== "" && Number.isFinite(maxTokVal))
        modelSettingsOverrides.max_tokens = maxTokVal;

      const model = {
        name: draft.model_name,
        model_settings_preset: draft.model_settings_preset || null,
        model_settings:
          Object.keys(modelSettingsOverrides).length > 0 ? modelSettingsOverrides : null,
        model_config_preset: draft.model_config_preset || null,
        // Preserve existing model_config_overrides (UI doesn't edit this).
        model_config_overrides: base?.model?.model_config_overrides ?? null,
      };

      const subagents = {
        include_builtin: draft.subagents_include_builtin,
        async_enabled: draft.subagents_async_enabled,
        // Preserve existing subagent refs (UI doesn't edit these).
        ...(base?.subagents?.refs?.length ? { refs: base.subagents.refs } : {}),
      };

      const environment = {
        mode: draft.env_mode,
        // Preserve workspace/project references from existing preset.
        ...(base?.environment?.workspace_id ? { workspace_id: base.environment.workspace_id } : {}),
        ...(base?.environment?.project_ids?.length
          ? { project_ids: base.environment.project_ids }
          : {}),
        ...(draft.env_mode === "sandbox"
          ? {
              container_id: draft.env_container_id || null,
              container_workdir: draft.env_container_workdir || "/workspace",
            }
          : {}),
      };

      const tool_config = {
        skip_url_verification: draft.tool_skip_url_verification,
        enable_load_document: draft.tool_enable_load_document,
        image_understanding_model: draft.tool_image_model || null,
        // Preserve model_settings dicts (UI doesn't edit these).
        ...(base?.tool_config?.image_understanding_model_settings
          ? {
              image_understanding_model_settings:
                base.tool_config.image_understanding_model_settings,
            }
          : {}),
        video_understanding_model: draft.tool_video_model || null,
        ...(base?.tool_config?.video_understanding_model_settings
          ? {
              video_understanding_model_settings:
                base.tool_config.video_understanding_model_settings,
            }
          : {}),
      };

      const mcp_servers = draft.mcp_servers
        .filter((s) => s.url.trim())
        .map((s) => {
          let headers: Record<string, string> | null = null;
          if (s.headers.trim()) {
            try {
              headers = JSON.parse(s.headers);
            } catch {
              /* ignore */
            }
          }
          const timeoutVal = parseFloat(s.timeout);
          return {
            url: s.url,
            transport: s.transport,
            headers,
            tool_prefix: s.tool_prefix || null,
            timeout: s.timeout !== "" && Number.isFinite(timeoutVal) ? timeoutVal : null,
            description: s.description.trim() || null,
          };
        });

      const payload = {
        name: draft.name,
        description: draft.description || null,
        is_default: draft.is_default,
        model,
        system_prompt: draft.system_prompt,
        toolsets,
        subagents,
        environment,
        tool_config,
        mcp_servers,
      };

      if (mode === "view" && selectedPreset) {
        const updated = await updatePreset(selectedPreset.preset_id, payload);
        setPresets((ps) => ps.map((p) => (p.preset_id === updated.preset_id ? updated : p)));
        setSelectedId(updated.preset_id);
      } else {
        const created = await createPreset(payload);
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
            modelPresets={modelPresets}
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
  const [projectError, setProjectError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    setDraft(workspace ? workspaceToDraft(workspace) : emptyWorkspaceDraft());
    setNewProject("");
    setProjectError(null);
  }, [workspace?.workspace_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const addProject = () => {
    const val = newProject.trim();
    if (!val) return;
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(val) || val.length > 64) {
      setProjectError("Use letters, numbers, dots, hyphens, underscores only");
      return;
    }
    if (draft.projects.includes(val)) {
      setProjectError("Project already exists");
      return;
    }
    setDraft((d) => ({ ...d, projects: [...d.projects, val] }));
    setNewProject("");
    setProjectError(null);
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

          {/* Projects */}
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Projects
            </h3>
            <p className="text-xs text-muted-foreground">
              Each project creates a managed directory on the server that the agent can access.
            </p>
            {draft.projects.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No projects yet. Add one to give the agent file system access.
              </p>
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
                onChange={(e) => {
                  setNewProject(e.target.value);
                  setProjectError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addProject();
                  }
                }}
                placeholder="New project name (e.g. my-app)"
                className={[
                  "flex-1 font-mono text-xs",
                  projectError ? "border-destructive" : "",
                ].join(" ")}
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
            {projectError && <p className="text-xs text-destructive">{projectError}</p>}
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
// Account tab
// ============================================================================

/** Dialog that displays a secret once (password or API key). */
function SecretRevealDialog({
  open,
  title,
  description,
  secret,
  onClose,
}: {
  open: boolean;
  title: string;
  description: string;
  secret: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex items-start gap-2 rounded-md border border-border bg-muted px-3 py-2">
          <code className="flex-1 text-sm font-mono break-all select-all whitespace-pre-line">
            {secret}
          </code>
          <Button variant="ghost" size="sm" className="shrink-0" onClick={() => void handleCopy()}>
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChangePasswordForm() {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const mismatch = confirmPassword !== "" && newPassword !== confirmPassword;
  const canSubmit =
    oldPassword.length > 0 && newPassword.length >= 8 && newPassword === confirmPassword && !saving;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword });
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Current password is incorrect." : err.detail);
      } else {
        setError("Failed to change password.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3 max-w-sm">
      <div className="space-y-1.5">
        <Label htmlFor="old-pw">Current password</Label>
        <div className="relative">
          <Input
            id="old-pw"
            type={showOld ? "text" : "password"}
            value={oldPassword}
            onChange={(e) => {
              setOldPassword(e.target.value);
              setError(null);
              setSuccess(false);
            }}
            autoComplete="current-password"
          />
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
            onClick={() => setShowOld(!showOld)}
          >
            {showOld ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="new-pw">New password</Label>
        <div className="relative">
          <Input
            id="new-pw"
            type={showNew ? "text" : "password"}
            value={newPassword}
            onChange={(e) => {
              setNewPassword(e.target.value);
              setError(null);
              setSuccess(false);
            }}
            autoComplete="new-password"
            placeholder="At least 8 characters"
          />
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
            onClick={() => setShowNew(!showNew)}
          >
            {showNew ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="confirm-pw">Confirm new password</Label>
        <Input
          id="confirm-pw"
          type="password"
          value={confirmPassword}
          onChange={(e) => {
            setConfirmPassword(e.target.value);
            setError(null);
            setSuccess(false);
          }}
          autoComplete="new-password"
        />
        {mismatch && <p className="text-xs text-destructive">Passwords do not match.</p>}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {success && <p className="text-sm text-primary">Password changed successfully.</p>}
      <Button type="submit" size="sm" disabled={!canSubmit}>
        {saving ? "Saving..." : "Change password"}
      </Button>
    </form>
  );
}

function ApiKeysSection({ userId }: { userId?: string }) {
  const [keys, setKeys] = useState<ApiKeyResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [revealedKey, setRevealedKey] = useState<ApiKeyCreateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setKeys(await listKeys(userId));
    } catch {
      setError("Failed to load API keys.");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    if (!newKeyName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const created = await createKey({ name: newKeyName.trim() });
      setRevealedKey(created);
      setNewKeyName("");
      void load();
    } catch {
      setError("Failed to create API key.");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    setError(null);
    try {
      await revokeKey(keyId);
      void load();
    } catch {
      setError("Failed to revoke key.");
    }
  };

  return (
    <div className="space-y-4">
      {/* Create */}
      <div className="flex gap-2 max-w-sm">
        <Input
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void handleCreate();
            }
          }}
          placeholder="Key name (e.g. my-script)"
          className="flex-1 text-sm"
        />
        <Button
          size="sm"
          onClick={() => void handleCreate()}
          disabled={creating || !newKeyName.trim()}
        >
          {creating ? "Creating..." : "Create"}
        </Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {/* List */}
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : keys.length === 0 ? (
        <p className="text-sm text-muted-foreground">No API keys.</p>
      ) : (
        <div className="space-y-1.5">
          {keys.map((k) => (
            <div
              key={k.key_id}
              className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm"
            >
              <KeyRound className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{k.name}</span>
                  {!k.is_active && (
                    <Badge variant="secondary" className="text-[10px] px-1 py-0">
                      revoked
                    </Badge>
                  )}
                </div>
                <span className="text-xs text-muted-foreground font-mono">{k.key_prefix}...</span>
              </div>
              {k.is_active && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive h-7 text-xs"
                  onClick={() => void handleRevoke(k.key_id)}
                >
                  Revoke
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Reveal new key */}
      {revealedKey && (
        <SecretRevealDialog
          open
          title="API Key Created"
          description="Copy this key now. You will not be able to see it again."
          secret={revealedKey.key}
          onClose={() => setRevealedKey(null)}
        />
      )}
    </div>
  );
}

function AccountTab() {
  const user = useAppStore((s) => s.user);

  return (
    <ScrollArea className="h-full">
      <div className="px-6 py-5 space-y-8 max-w-2xl">
        {/* Profile info */}
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Profile
          </h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">User ID</span>
              <p className="font-medium font-mono">{user?.user_id ?? "-"}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Display Name</span>
              <p className="font-medium">{user?.display_name ?? "-"}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Role</span>
              <p className="font-medium capitalize">{user?.role ?? "-"}</p>
            </div>
          </div>
        </section>

        <Separator />

        {/* Change password */}
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Change Password
          </h3>
          <ChangePasswordForm />
        </section>

        <Separator />

        {/* API Keys */}
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            API Keys
          </h3>
          <p className="text-xs text-muted-foreground">
            API keys can be used for programmatic access. They do not expire unless revoked.
          </p>
          <ApiKeysSection userId={user?.user_id} />
        </section>

        <div className="h-4" />
      </div>
    </ScrollArea>
  );
}

// ============================================================================
// Users tab (admin only)
// ============================================================================

function CreateUserDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (result: UserCreateResponse) => void;
}) {
  const [userId, setUserId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!userId.trim() || !displayName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const result = await createUser({
        user_id: userId.trim(),
        display_name: displayName.trim(),
        role,
      });
      onCreated(result);
      setUserId("");
      setDisplayName("");
      setRole("user");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("User ID already exists.");
      } else {
        setError("Failed to create user.");
      }
    } finally {
      setCreating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create User</DialogTitle>
          <DialogDescription>A random password and API key will be generated.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="new-user-id">User ID</Label>
            <Input
              id="new-user-id"
              value={userId}
              onChange={(e) => {
                setUserId(e.target.value);
                setError(null);
              }}
              placeholder="alice"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-display-name">Display Name</Label>
            <Input
              id="new-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Alice"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="role"
                  checked={role === "user"}
                  onChange={() => setRole("user")}
                  className="accent-primary"
                />
                <span className="text-sm">User</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="role"
                  checked={role === "admin"}
                  onChange={() => setRole("admin")}
                  className="accent-primary"
                />
                <span className="text-sm">Admin</span>
              </label>
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleCreate()}
            disabled={creating || !userId.trim() || !displayName.trim()}
          >
            {creating ? "Creating..." : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UsersTab() {
  const currentUser = useAppStore((s) => s.user);
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<{
    title: string;
    description: string;
    secret: string;
  } | null>(null);
  const [confirmDeactivate, setConfirmDeactivate] = useState<UserResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setUsers(await listUsers());
    } catch {
      setError("Failed to load users.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreated = (result: UserCreateResponse) => {
    setCreateDialogOpen(false);
    setRevealedSecret({
      title: `User "${result.user.display_name}" Created`,
      description: `Share these credentials with the user. The password cannot be retrieved later.`,
      secret: `User ID: ${result.user.user_id}\nPassword: ${result.password}\nAPI Key: ${result.api_key.key}`,
    });
    void load();
  };

  const handleResetPassword = async (userId: string) => {
    setError(null);
    try {
      const res = await resetPassword(userId);
      setRevealedSecret({
        title: "Password Reset",
        description: `New password for "${userId}". Share it with the user securely.`,
        secret: res.password,
      });
    } catch {
      setError("Failed to reset password.");
    }
  };

  const handleDeactivate = async (userId: string) => {
    setConfirmDeactivate(null);
    setError(null);
    try {
      await deactivateUser(userId);
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Cannot deactivate your own account.");
      } else {
        setError("Failed to deactivate user.");
      }
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-border shrink-0">
        <span className="flex-1 text-sm font-semibold">Users</span>
        <Button size="sm" onClick={() => setCreateDialogOpen(true)} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          Create User
        </Button>
      </div>

      {error && <ErrorBanner message={error} />}

      <ScrollArea className="flex-1 min-h-0">
        <div className="px-6 py-4 space-y-1.5 max-w-3xl">
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-14 w-full rounded-md" />
              ))}
            </div>
          ) : users.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">No users found.</p>
          ) : (
            users.map((u) => {
              const isSelf = u.user_id === currentUser?.user_id;
              const handleRoleChange = async (newRole: "admin" | "user") => {
                if (newRole === u.role) return;
                setError(null);
                try {
                  await updateUser(u.user_id, { role: newRole });
                  void load();
                } catch {
                  setError("Failed to update role.");
                }
              };
              return (
                <div
                  key={u.user_id}
                  className="flex items-center gap-4 rounded-md border border-border px-4 py-3"
                >
                  <div className="flex items-center justify-center h-8 w-8 rounded-full bg-muted shrink-0">
                    {u.role === "admin" ? (
                      <Shield className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <User className="h-4 w-4 text-muted-foreground" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{u.display_name}</span>
                      <span className="text-xs text-muted-foreground font-mono">({u.user_id})</span>
                      {isSelf && (
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          you
                        </Badge>
                      )}
                      {!u.is_active && (
                        <Badge variant="destructive" className="text-[10px] px-1.5 py-0">
                          deactivated
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      {isSelf ? (
                        <Badge variant="secondary" className="text-[10px] px-1.5 py-0 capitalize">
                          {u.role}
                        </Badge>
                      ) : (
                        <Select
                          value={u.role}
                          onValueChange={(v) => void handleRoleChange(v as "admin" | "user")}
                        >
                          <SelectTrigger className="h-5 w-20 text-[10px] px-1.5 py-0">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="user">user</SelectItem>
                            <SelectItem value="admin">admin</SelectItem>
                          </SelectContent>
                        </Select>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {u.is_active && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs gap-1"
                        onClick={() => void handleResetPassword(u.user_id)}
                      >
                        <RotateCcw className="h-3 w-3" />
                        Reset pw
                      </Button>
                    )}
                    {u.is_active && !isSelf && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs gap-1 text-destructive hover:text-destructive"
                        onClick={() => setConfirmDeactivate(u)}
                      >
                        <UserX className="h-3 w-3" />
                        Deactivate
                      </Button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>

      {/* Dialogs */}
      <CreateUserDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onCreated={handleCreated}
      />

      {revealedSecret && (
        <SecretRevealDialog
          open
          title={revealedSecret.title}
          description={revealedSecret.description}
          secret={revealedSecret.secret}
          onClose={() => setRevealedSecret(null)}
        />
      )}

      {confirmDeactivate && (
        <DeleteConfirmDialog
          open
          name={confirmDeactivate.display_name}
          onConfirm={() => void handleDeactivate(confirmDeactivate.user_id)}
          onCancel={() => setConfirmDeactivate(null)}
        />
      )}
    </div>
  );
}

// ============================================================================
// Main Settings page
// ============================================================================

export default function Settings() {
  const navigate = useNavigate();
  const user = useAppStore((s) => s.user);
  const isAdmin = user?.role === "admin";

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
          <TabsTrigger value="account">Account</TabsTrigger>
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
        </TabsList>
        <TabsContent value="presets" className="flex-1 min-h-0 mt-3">
          <PresetsTab />
        </TabsContent>
        <TabsContent value="workspaces" className="flex-1 min-h-0 mt-3">
          <WorkspacesTab />
        </TabsContent>
        <TabsContent value="account" className="flex-1 min-h-0 mt-3">
          <AccountTab />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="users" className="flex-1 min-h-0 mt-3">
            <UsersTab />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
