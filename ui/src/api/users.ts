import { api } from "./client";
import type {
  UserResponse,
  UserCreate,
  UserCreateResponse,
  UserUpdate,
  ResetPasswordResponse,
} from "./types";

export async function listUsers(): Promise<UserResponse[]> {
  return api.get<UserResponse[]>("/api/users/list");
}

export async function getUser(userId: string): Promise<UserResponse> {
  return api.get<UserResponse>(`/api/users/${userId}/get`);
}

export async function createUser(body: UserCreate): Promise<UserCreateResponse> {
  return api.post<UserCreateResponse>("/api/users/create", body);
}

export async function updateUser(userId: string, body: UserUpdate): Promise<UserResponse> {
  return api.post<UserResponse>(`/api/users/${userId}/update`, body);
}

export async function deactivateUser(userId: string): Promise<UserResponse> {
  return api.post<UserResponse>(`/api/users/${userId}/deactivate`);
}

export async function resetPassword(userId: string): Promise<ResetPasswordResponse> {
  return api.post<ResetPasswordResponse>(`/api/users/${userId}/reset-password`);
}
