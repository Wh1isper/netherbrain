import { api } from "./client";
import type {
  PresetResponse,
  PresetCreate,
  PresetUpdate,
  ToolsetInfo,
  ModelPresetsResponse,
} from "./types";

export async function listPresets(): Promise<PresetResponse[]> {
  return api.get<PresetResponse[]>("/api/presets/list");
}

export async function getPreset(id: string): Promise<PresetResponse> {
  return api.get<PresetResponse>(`/api/presets/${id}/get`);
}

export async function createPreset(body: PresetCreate): Promise<PresetResponse> {
  return api.post<PresetResponse>("/api/presets/create", body);
}

export async function updatePreset(id: string, body: PresetUpdate): Promise<PresetResponse> {
  return api.post<PresetResponse>(`/api/presets/${id}/update`, body);
}

export async function deletePreset(id: string): Promise<void> {
  return api.post<void>(`/api/presets/${id}/delete`);
}

export async function listToolsets(): Promise<ToolsetInfo[]> {
  return api.get<ToolsetInfo[]>("/api/toolsets");
}

export async function listModelPresets(): Promise<ModelPresetsResponse> {
  return api.get<ModelPresetsResponse>("/api/model-presets");
}
