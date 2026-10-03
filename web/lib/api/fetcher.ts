/**
 * Mutator used by the generated API client (orval). Adds credentials, JSON headers, the access
 * token and the same-origin marker; refreshes the session once on 401 and retries; and turns error
 * envelopes into `ApiError`s so TanStack Query can handle them.
 */
import { accessTokenStale, getAccessToken, refreshSession } from "@/lib/auth/session";

import { ApiError, NETWORK_ERROR, UNKNOWN_ERROR, isErrorBody } from "./errors";

/** Emitted when the session ends (refresh failed after a 401); the AuthProvider listens. */
export const SESSION_ENDED_EVENT = "app:session-ended";
const NO_REFRESH_PATHS = ["/api/v1/auth/token/refresh/", "/api/v1/auth/logout/"];

function baseUrl(): string {
  // Browser: same origin (Next rewrites /api/* to Django). Server components: call Django directly.
  if (typeof window !== "undefined") return "";
  return process.env.API_INTERNAL_URL ?? "http://localhost:8000";
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function buildHeaders(options: RequestInit, token: string | null): Headers {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  // Cookie-authenticated auth endpoints require it (CSRF defence, ADR-025); harmless elsewhere.
  headers.set("X-Requested-With", "fetch");
  if (
    options.body !== undefined &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  // The server answers in the language on screen (ADR-060): its messages and field errors.
  if (typeof document !== "undefined" && document.documentElement.lang) {
    headers.set("Accept-Language", document.documentElement.lang);
  }
  return headers;
}

async function send(url: string, options: RequestInit): Promise<Response> {
  try {
    return await fetch(`${baseUrl()}${url}`, {
      ...options,
      headers: buildHeaders(options, typeof window !== "undefined" ? getAccessToken() : null),
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, { code: NETWORK_ERROR, message: "Network unavailable", details: {} });
  }
}

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const inBrowser = typeof window !== "undefined";
  const canRefresh = inBrowser && !NO_REFRESH_PATHS.some((p) => url.startsWith(p));
  if (canRefresh && getAccessToken() !== null && accessTokenStale()) await refreshSession();

  let response = await send(url, options);
  if (response.status === 401 && canRefresh && getAccessToken() !== null) {
    if (await refreshSession()) {
      response = await send(url, options);
    } else {
      window.dispatchEvent(new Event(SESSION_ENDED_EVENT));
    }
  }

  const data = await parseBody(response);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      isErrorBody(data)
        ? data.error
        : { code: UNKNOWN_ERROR, message: response.statusText, details: {} },
    );
  }
  return { data, status: response.status, headers: response.headers } as T;
}

export default apiFetch;
