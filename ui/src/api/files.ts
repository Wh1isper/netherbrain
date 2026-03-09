/**
 * Files API client — wraps /api/files/{project_id} endpoints.
 */

import { api, getAuthToken } from "./client";
import type {
  FileListResponse,
  FileReadResponse,
  FileWriteResponse,
  UploadResponse,
} from "./types";

const base = (projectId: string) => `/api/files/${projectId}`;

/** List directory contents. Pass path="" or omit for root. */
export function listFiles(projectId: string, path = ""): Promise<FileListResponse> {
  return api.get<FileListResponse>(`${base(projectId)}/list`, { path });
}

/** Read file content. maxSize defaults to server default. */
export function readFile(
  projectId: string,
  path: string,
  maxSize?: number,
): Promise<FileReadResponse> {
  return api.get<FileReadResponse>(`${base(projectId)}/read`, {
    path,
    ...(maxSize !== undefined ? { max_size: maxSize } : {}),
  });
}

/** Write (overwrite) a file. */
export function writeFile(
  projectId: string,
  path: string,
  content: string,
): Promise<FileWriteResponse> {
  return api.post<FileWriteResponse>(`${base(projectId)}/write`, { path, content });
}

/**
 * Upload one or more files to a directory.
 * Uses raw fetch with FormData (multipart), not the JSON api client.
 */
export async function uploadFiles(
  projectId: string,
  path: string,
  files: File[],
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("path", path);
  for (const file of files) {
    form.append("files", file, file.name);
  }

  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${base(projectId)}/upload`, {
    method: "POST",
    headers,
    body: form,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = (await res.json()) as { detail?: string };
      if (json.detail) detail = json.detail;
    } catch {
      // ignore
    }
    throw new Error(`Upload failed (${res.status}): ${detail}`);
  }

  return res.json() as Promise<UploadResponse>;
}

/** Returns a URL suitable for <img src> or download links. */
export function getDownloadUrl(projectId: string, path: string): string {
  const token = getAuthToken();
  const url = new URL(`${base(projectId)}/download`, window.location.origin);
  url.searchParams.set("path", path);
  if (token) {
    // Token in query param for direct links (img src etc.)
    url.searchParams.set("token", token);
  }
  return url.toString();
}

/** Delete one or more files or directories. */
export async function deletePaths(
  projectId: string,
  paths: string[],
): Promise<{ deleted: number; errors: string[] }> {
  return api.post<{ deleted: number; errors: string[] }>(`${base(projectId)}/delete`, { paths });
}

/** Create a new directory. */
export async function createDirectory(projectId: string, path: string): Promise<{ path: string }> {
  return api.post<{ path: string }>(`${base(projectId)}/mkdir`, { path });
}

/** Download multiple paths as a zip archive blob. */
export async function downloadArchive(projectId: string, paths: string[]): Promise<Blob> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${base(projectId)}/download-archive`, {
    method: "POST",
    headers,
    body: JSON.stringify({ paths }),
  });

  if (!res.ok) {
    throw new Error(`Archive download failed (${res.status}): ${res.statusText}`);
  }

  return res.blob();
}
