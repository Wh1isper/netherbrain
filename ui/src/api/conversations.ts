import { api, getAuthToken } from "./client";
import type {
  ConversationResponse,
  ConversationDetailResponse,
  ConversationUpdate,
  ConversationRunRequest,
  ConversationForkRequest,
  ConversationFireRequest,
  PrepareForkRequest,
  PrepareForkResponse,
  SteerRequest,
  TurnsResponse,
  MailboxMessageResponse,
  SearchResponse,
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

export async function getConversationTurns(
  id: string,
  opts?: { includeDisplay?: boolean; limit?: number; before?: string },
): Promise<TurnsResponse> {
  const params: Record<string, string | number | boolean> = {};
  if (opts?.includeDisplay) params["include_display"] = true;
  if (opts?.limit) params["limit"] = opts.limit;
  if (opts?.before) params["before"] = opts.before;
  return api.get<TurnsResponse>(`/api/conversations/${id}/turns`, params);
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

export async function streamConversationEvents(
  id: string,
  opts?: { lastEventId?: string; signal?: AbortSignal },
): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
  };
  const token = getAuthToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts?.lastEventId) headers["Last-Event-ID"] = opts.lastEventId;

  return fetch(`/api/conversations/${id}/events`, {
    method: "GET",
    headers,
    signal: opts?.signal,
  });
}

export async function interruptConversation(id: string): Promise<void> {
  return api.post<void>(`/api/conversations/${id}/interrupt`);
}

export async function steerConversation(id: string, body: SteerRequest): Promise<void> {
  return api.post<void>(`/api/conversations/${id}/steer`, body);
}

export async function prepareFork(
  id: string,
  body: PrepareForkRequest = {},
): Promise<PrepareForkResponse> {
  return api.post<PrepareForkResponse>(`/api/conversations/${id}/prepare-fork`, body);
}

export async function forkConversation(
  id: string,
  body: ConversationForkRequest,
): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAuthToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return fetch(`/api/conversations/${id}/fork`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

export async function fireConversation(
  id: string,
  body: ConversationFireRequest,
): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAuthToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return fetch(`/api/conversations/${id}/fire`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

export async function getMailbox(
  id: string,
  opts?: { pendingOnly?: boolean; limit?: number; offset?: number },
): Promise<MailboxMessageResponse[]> {
  const params: Record<string, string | number | boolean> = {};
  if (opts?.pendingOnly) params["pending_only"] = true;
  if (opts?.limit) params["limit"] = opts.limit;
  if (opts?.offset) params["offset"] = opts.offset;
  return api.get<MailboxMessageResponse[]>(`/api/conversations/${id}/mailbox`, params);
}

export async function searchConversations(opts: {
  q: string;
  limit?: number;
  offset?: number;
}): Promise<SearchResponse> {
  const params: Record<string, string | number> = { q: opts.q };
  if (opts.limit) params["limit"] = opts.limit;
  if (opts.offset) params["offset"] = opts.offset;
  return api.get<SearchResponse>("/api/conversations/search", params);
}

export async function summarizeConversation(id: string): Promise<ConversationResponse> {
  return api.post<ConversationResponse>(`/api/conversations/${id}/summarize`);
}
