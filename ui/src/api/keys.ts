import { api } from "./client";
import type { ApiKeyResponse, ApiKeyCreate, ApiKeyCreateResponse } from "./types";

export async function listKeys(userId?: string): Promise<ApiKeyResponse[]> {
  const params: Record<string, string | undefined> = {};
  if (userId) params["user_id"] = userId;
  return api.get<ApiKeyResponse[]>("/api/keys/list", params);
}

export async function createKey(body: ApiKeyCreate): Promise<ApiKeyCreateResponse> {
  return api.post<ApiKeyCreateResponse>("/api/keys/create", body);
}

export async function revokeKey(keyId: string): Promise<ApiKeyResponse> {
  return api.post<ApiKeyResponse>(`/api/keys/${keyId}/revoke`);
}
