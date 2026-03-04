import { api } from "./client";
import type { WorkspaceResponse, WorkspaceCreate, WorkspaceUpdate } from "./types";

export async function listWorkspaces(): Promise<WorkspaceResponse[]> {
  return api.get<WorkspaceResponse[]>("/api/workspaces/list");
}

export async function getWorkspace(id: string): Promise<WorkspaceResponse> {
  return api.get<WorkspaceResponse>(`/api/workspaces/${id}/get`);
}

export async function createWorkspace(body: WorkspaceCreate): Promise<WorkspaceResponse> {
  return api.post<WorkspaceResponse>("/api/workspaces/create", body);
}

export async function updateWorkspace(
  id: string,
  body: WorkspaceUpdate,
): Promise<WorkspaceResponse> {
  return api.post<WorkspaceResponse>(`/api/workspaces/${id}/update`, body);
}

export async function deleteWorkspace(id: string): Promise<void> {
  return api.post<void>(`/api/workspaces/${id}/delete`);
}

/**
 * Find or auto-create the default webui workspace.
 * Returns both the default workspace and the full workspace list,
 * avoiding a redundant second listWorkspaces call.
 */
export async function ensureDefaultWorkspace(): Promise<{
  defaultWs: WorkspaceResponse;
  all: WorkspaceResponse[];
}> {
  let all = await listWorkspaces();
  const existing = all.find((w) => w.metadata?.source === "webui" && w.metadata?.default === true);
  if (existing) return { defaultWs: existing, all };

  const created = await createWorkspace({
    workspace_id: "webui-default",
    name: "Default",
    projects: ["webui"],
    metadata: { source: "webui", default: true },
  });
  all = [...all, created];
  return { defaultWs: created, all };
}
