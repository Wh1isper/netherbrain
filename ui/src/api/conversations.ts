import { api, getAuthToken } from "./client";
import type {
  ConversationResponse,
  ConversationDetailResponse,
  ConversationUpdate,
  ConversationRunRequest,
  SteerRequest,
  TurnResponse,
} from "./types";

export async function listConversations(opts?: {
  workspaceId?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ConversationResponse[]> {
  const params: Record<string, string | number | undefined> = {
    limit: opts?.limit ?? 50,
    offset: opts?.offset ?? 0,
  };
  if (opts?.status) params["status"] = opts.status;
  if (opts?.workspaceId) {
    params["metadata_contains"] = JSON.stringify({
      workspace_id: opts.workspaceId,
    });
  }
  return api.get<ConversationResponse[]>("/api/conversations/list", params);
}

export async function getConversation(id: string): Promise<ConversationDetailResponse> {
  return api.get<ConversationDetailResponse>(`/api/conversations/${id}/get`);
}

export async function updateConversation(
  id: string,
  body: ConversationUpdate,
): Promise<ConversationResponse> {
  return api.post<ConversationResponse>(`/api/conversations/${id}/update`, body);
}

export async function getConversationTurns(id: string): Promise<TurnResponse[]> {
  return api.get<TurnResponse[]>(`/api/conversations/${id}/turns`);
}

export async function runConversation(body: ConversationRunRequest): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAuthToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return fetch("/api/conversations/run", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

export async function interruptConversation(id: string): Promise<void> {
  return api.post<void>(`/api/conversations/${id}/interrupt`);
}

export async function steerConversation(id: string, body: SteerRequest): Promise<void> {
  return api.post<void>(`/api/conversations/${id}/steer`, body);
}
