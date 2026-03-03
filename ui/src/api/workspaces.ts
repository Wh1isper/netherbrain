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
 * Identifies it by metadata: { source: "webui", default: true }
 */
export async function ensureDefaultWorkspace(): Promise<WorkspaceResponse> {
  const all = await listWorkspaces();
  const existing = all.find((w) => w.metadata?.source === "webui" && w.metadata?.default === true);
  if (existing) return existing;

  return createWorkspace({
    workspace_id: "webui-default",
    name: "Default",
    projects: ["webui"],
    metadata: { source: "webui", default: true },
  });
}
