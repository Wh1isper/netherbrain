import { api } from "./client";
import type { LoginRequest, LoginResponse, UserResponse, ChangePasswordRequest } from "./types";

export async function login(body: LoginRequest): Promise<LoginResponse> {
  return api.post<LoginResponse>("/api/auth/login", body);
}

export async function getMe(): Promise<UserResponse> {
  return api.get<UserResponse>("/api/auth/me");
}

export async function changePassword(body: ChangePasswordRequest): Promise<void> {
  return api.post<void>("/api/auth/change-password", body);
}
