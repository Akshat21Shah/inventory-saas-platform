/**
 * Authenticated file downloads (exports, templates, error reports). The generated client reads
 * bodies as text, which would corrupt binary files, so these go through `fetch` with the same
 * access token and a one-time refresh.
 */
import { accessTokenStale, getAccessToken, refreshSession } from "@/lib/auth/session";

import { ApiError, UNKNOWN_ERROR, isErrorBody } from "./errors";

function filenameFrom(response: Response, fallback: string): string {
  const header = response.headers.get("Content-Disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match?.[1] ? decodeURIComponent(match[1]) : fallback;
}

async function get(url: string): Promise<Response> {
  const token = getAccessToken();
  return fetch(url, {
    headers: {
      "X-Requested-With": "fetch",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    credentials: "include",
  });
}

/** Fetch `url` and save it; throws `ApiError` (with the server's code) when it fails. */
export async function downloadFile(url: string, fallbackName: string): Promise<void> {
  if (getAccessToken() !== null && accessTokenStale()) await refreshSession();
  let response = await get(url);
  if (response.status === 401 && (await refreshSession())) response = await get(url);
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // not JSON
    }
    throw new ApiError(
      response.status,
      isErrorBody(body)
        ? body.error
        : { code: UNKNOWN_ERROR, message: response.statusText, details: {} },
    );
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filenameFrom(response, fallbackName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}
