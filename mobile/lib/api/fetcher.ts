/**
 * Mutator used by the generated API client (orval), the app's twin of the web's
 * (`web/lib/api/fetcher.ts`): JSON headers, the access token, the app's language and version;
 * one refresh on a 401, then the request again; error envelopes become `ApiError`s.
 */
import { APP_VERSION, config } from "@/lib/config";
import { sessionEnded, updateRequired } from "@/lib/events";
import { currentLanguage } from "@/lib/i18n/language";
import { accessTokenStale, getAccessToken, refreshSession } from "@/lib/auth/session";
import { ApiError, NETWORK_ERROR, UNKNOWN_ERROR, isErrorBody } from "@/lib/shared/errors";

const NO_REFRESH_PATHS = ["/api/v1/auth/token/refresh/", "/api/v1/auth/logout/"];

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
  if (
    options.body !== undefined &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept-Language", currentLanguage());
  headers.set("X-App-Version", APP_VERSION);
  return headers;
}

async function send(url: string, options: RequestInit): Promise<Response> {
  try {
    return await fetch(`${config.apiUrl}${url}`, {
      ...options,
      headers: buildHeaders(options, getAccessToken()),
    });
  } catch {
    throw new ApiError(0, { code: NETWORK_ERROR, message: "Network unavailable", details: {} });
  }
}

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const canRefresh = !NO_REFRESH_PATHS.some((path) => url.startsWith(path));
  if (canRefresh && getAccessToken() !== null && accessTokenStale()) await refreshSession();
  let response = await send(url, options);
  if (response.status === 401 && canRefresh && getAccessToken() !== null) {
    if (await refreshSession()) {
      response = await send(url, options);
    } else {
      sessionEnded.emit();
    }
  }
  const data = await parseBody(response);
  if (!response.ok) {
    if (response.status === 426) updateRequired.emit();
    throw new ApiError(
      response.status,
      isErrorBody(data)
        ? data.error
        : { code: UNKNOWN_ERROR, message: String(response.status), details: {} },
    );
  }
  return { data, status: response.status, headers: response.headers } as T;
}

export default apiFetch;
