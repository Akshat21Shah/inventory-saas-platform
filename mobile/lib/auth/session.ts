/**
 * The app's session (ADR-061 item 4): the refresh token in Android's secure storage (Keystore),
 * the access token only in memory. Refreshing rotates the refresh token; one refresh runs at a
 * time however many requests need it.
 */
import * as SecureStore from "expo-secure-store";

import { APP_VERSION, config } from "@/lib/config";

const REFRESH_KEY = "session.refresh";
const TENANT_KEY = "session.tenant";
const STALE_MS = 30_000;

export interface Tokens {
  access: string;
  access_expires_at: string;
  refresh: string;
}

let access: { token: string; expiresAt: number } | null = null;
let refreshing: Promise<boolean> | null = null;

export function getAccessToken(): string | null {
  return access?.token ?? null;
}

export function accessTokenStale(): boolean {
  return access !== null && access.expiresAt - Date.now() < STALE_MS;
}

function keep(token: string, expiresAt: string) {
  access = { token, expiresAt: Date.parse(expiresAt) };
}

/** Signed in: keep the session. */
export async function startSession(tokens: Tokens): Promise<void> {
  keep(tokens.access, tokens.access_expires_at);
  await SecureStore.setItemAsync(REFRESH_KEY, tokens.refresh);
}

/** Which distributor the session is for (its web address name), for branding and links. */
export async function setSessionTenant(tenantSlug: string): Promise<void> {
  await SecureStore.setItemAsync(TENANT_KEY, tenantSlug);
}

export async function sessionTenant(): Promise<string | null> {
  return SecureStore.getItemAsync(TENANT_KEY);
}

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${config.apiUrl}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-App-Version": APP_VERSION,
    },
    body: JSON.stringify(body),
  });
}

async function doRefresh(): Promise<boolean> {
  const refresh = await SecureStore.getItemAsync(REFRESH_KEY);
  if (!refresh) return false;
  let response: Response;
  try {
    response = await post("/api/v1/auth/token/refresh/", { refresh });
  } catch {
    return access !== null; // offline: keep what we have; the next request tries again
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) await clear();
    return false;
  }
  const body = (await response.json()) as {
    access: string;
    access_expires_at: string;
    refresh: string;
  };
  keep(body.access, body.access_expires_at);
  await SecureStore.setItemAsync(REFRESH_KEY, body.refresh);
  return true;
}

/** A new access token (and refresh token). False when the session is over. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= doRefresh().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

/** On start: is there a session to carry on? */
export async function restoreSession(): Promise<boolean> {
  if (!(await SecureStore.getItemAsync(REFRESH_KEY))) return false;
  return (await refreshSession()) || access !== null;
}

/** Whether a stored session exists (it may still need a refresh). */
export async function hasStoredSession(): Promise<boolean> {
  return (await SecureStore.getItemAsync(REFRESH_KEY)) !== null;
}

async function clear(): Promise<void> {
  access = null;
  await SecureStore.deleteItemAsync(REFRESH_KEY);
  await SecureStore.deleteItemAsync(TENANT_KEY);
}

/** Sign out: the server forgets the refresh token (best effort), the phone forgets everything. */
export async function endSession(): Promise<void> {
  const refresh = await SecureStore.getItemAsync(REFRESH_KEY);
  if (refresh) {
    try {
      await post("/api/v1/auth/logout/", { refresh });
    } catch {
      // offline: the token expires on its own
    }
  }
  await clear();
}
