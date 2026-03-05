/**
 * Base API client with JWT auth support and global 401 handling.
 */

let authToken: string | null = null;

/** Callback invoked on any 401 response (triggers logout). */
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

export function setOnUnauthorized(cb: (() => void) | null) {
  onUnauthorized = cb;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  params?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined) {
        url.searchParams.set(key, String(val));
      }
    }
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  const res = await fetch(url.toString(), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = (await res.json()) as { detail?: string };
      if (json.detail) detail = json.detail;
    } catch {
      // ignore parse errors
    }

    // Global 401 handler: clear auth and redirect to login.
    // Skip for /api/auth/login (login errors should be handled locally).
    if (res.status === 401 && !path.includes("/api/auth/login")) {
      onUnauthorized?.();
    }

    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
    request<T>("GET", path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
};
