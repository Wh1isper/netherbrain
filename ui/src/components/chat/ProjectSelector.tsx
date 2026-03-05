import { useState, useRef, useEffect, useCallback } from "react";
import { FolderOpen, Plus, Check, X, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface ProjectSelectorProps {
  /** Available projects from the current workspace. */
  projects: string[];
  /** Currently selected project paths (order matters: first = CWD). */
  selected: string[];
  onChange: (selected: string[]) => void;
  /** Callback to create a new project and add it to the workspace. */
  onCreateProject?: (name: string) => Promise<void>;
  disabled?: boolean;
}

const PROJECT_SLUG_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;

function isValidProjectName(name: string): boolean {
  return PROJECT_SLUG_RE.test(name) && name.length <= 64;
}

function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

export default function ProjectSelector({
  projects,
  selected,
  onChange,
  onCreateProject,
  disabled,
}: ProjectSelectorProps) {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (creating) {
      inputRef.current?.focus();
    }
  }, [creating]);

  const toggle = (project: string) => {
    if (disabled) return;
    if (selected.includes(project)) {
      onChange(selected.filter((p) => p !== project));
    } else {
      onChange([...selected, project]);
    }
  };

  const handleCreate = useCallback(async () => {
    const name = newName.trim();
    if (!name || !onCreateProject) return;
    if (!isValidProjectName(name)) {
      setNameError("Use letters, numbers, dots, hyphens, underscores only");
      return;
    }
    if (projects.includes(name)) {
      // Already exists -- just select it
      if (!selected.includes(name)) {
        onChange([...selected, name]);
      }
      setCreating(false);
      setNewName("");
      return;
    }
    setSaving(true);
    try {
      await onCreateProject(name);
      setCreating(false);
      setNewName("");
    } catch {
      // keep input open on error
    } finally {
      setSaving(false);
    }
  }, [newName, onCreateProject, projects, selected, onChange]);

  const cancelCreate = useCallback(() => {
    setCreating(false);
    setNewName("");
    setNameError(null);
  }, []);

  // Show nothing if no projects and no create capability
  if (projects.length === 0 && !onCreateProject) return null;

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex items-center gap-1.5 px-4 py-1.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          </TooltipTrigger>
          <TooltipContent side="top">
            <p>Select projects to mount. First selected = working directory.</p>
          </TooltipContent>
        </Tooltip>
        <div className="flex flex-wrap items-center gap-1">
          {projects.map((project) => {
            const isSelected = selected.includes(project);
            const isCwd = isSelected && selected[0] === project;
            return (
              <Tooltip key={project}>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => toggle(project)}
                    disabled={disabled}
                    className="focus:outline-none"
                  >
                    <Badge
                      variant={isSelected ? "default" : "outline"}
                      className={[
                        "text-xs px-2 py-0.5 transition-colors select-none",
                        disabled
                          ? "opacity-50 cursor-not-allowed"
                          : isSelected
                            ? "cursor-pointer hover:bg-primary/80"
                            : "cursor-pointer hover:bg-accent",
                      ].join(" ")}
                    >
                      {isCwd && (
                        <span className="mr-1 text-[10px] font-normal opacity-70">cwd</span>
                      )}
                      {basename(project)}
                    </Badge>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  <p>{project}</p>
                </TooltipContent>
              </Tooltip>
            );
          })}

          {/* Inline create */}
          {onCreateProject && !disabled && (
            <>
              {creating ? (
                <div className="flex items-center gap-1">
                  <Input
                    ref={inputRef}
                    value={newName}
                    onChange={(e) => {
                      setNewName(e.target.value);
                      setNameError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void handleCreate();
                      if (e.key === "Escape") cancelCreate();
                    }}
                    placeholder="project-name"
                    className={[
                      "h-6 w-32 text-xs font-mono px-2",
                      nameError ? "border-destructive" : "",
                    ].join(" ")}
                    disabled={saving}
                    title={nameError ?? undefined}
                  />
                  {saving ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                  ) : (
                    <>
                      <button
                        onClick={() => void handleCreate()}
                        disabled={!newName.trim()}
                        className="text-muted-foreground hover:text-primary transition-colors disabled:opacity-30"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={cancelCreate}
                        className="text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </div>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button onClick={() => setCreating(true)} className="focus:outline-none">
                      <Badge
                        variant="outline"
                        className="text-xs px-1.5 py-0.5 cursor-pointer hover:bg-accent transition-colors border-dashed"
                      >
                        <Plus className="h-3 w-3" />
                      </Badge>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>Create a new project</p>
                  </TooltipContent>
                </Tooltip>
              )}
            </>
          )}
        </div>
        {projects.length === 0 && !creating && (
          <span className="text-xs text-muted-foreground">No projects yet</span>
        )}
        {selected.length === 0 && projects.length > 0 && (
          <span className="text-xs text-muted-foreground">No projects mounted</span>
        )}
      </div>
    </TooltipProvider>
  );
}
