/**
 * Session-level API functions (steer / interrupt individual sessions).
 */
import { api } from "./client";
import type { SteerRequest } from "./types";

export async function steerSession(sessionId: string, body: SteerRequest): Promise<void> {
  return api.post<void>(`/api/sessions/${sessionId}/steer`, body);
}

export async function interruptSession(sessionId: string): Promise<void> {
  return api.post<void>(`/api/sessions/${sessionId}/interrupt`);
}
