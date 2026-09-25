/**
 * Mutator used by the generated API client (orval). Adds credentials, JSON headers and the
 * request id, and turns error envelopes into `ApiError`s so TanStack Query can handle them.
 */
import { ApiError, NETWORK_ERROR, UNKNOWN_ERROR, isErrorBody } from "./errors";

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

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (
    options.body !== undefined &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl()}${url}`, { ...options, headers, credentials: "include" });
  } catch {
    throw new ApiError(0, { code: NETWORK_ERROR, message: "Network unavailable", details: {} });
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
