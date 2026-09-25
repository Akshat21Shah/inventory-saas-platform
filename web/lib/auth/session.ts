/**
 * The browser session (ADR-025): the access token lives only in memory; the refresh token is an
 * httpOnly cookie the browser sends to /api/v1/auth/ on this host only.
 *
 * Refresh is single-flight per tab and serialised across tabs (Web Locks), because the server
 * rotates the refresh cookie: two tabs refreshing with the same cookie at once would log one out.
 */

type Listener = () => void;

const REFRESH_URL = "/api/v1/auth/token/refresh/";
const EXPIRY_MARGIN_MS = 30_000;

let accessToken: string | null = null;
let accessExpiresAt = 0;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** True when the token is missing or about to expire (refresh first). */
export function accessTokenStale(now = Date.now()): boolean {
  return accessToken === null || accessExpiresAt - EXPIRY_MARGIN_MS <= now;
}

export function setAccessToken(token: string, expiresAt: string | undefined): void {
  accessToken = token;
  accessExpiresAt = expiresAt ? Date.parse(expiresAt) : Date.now() + 5 * 60_000;
  notify();
}

export function clearAccessToken(): void {
  const had = accessToken !== null;
  accessToken = null;
  accessExpiresAt = 0;
  if (had) notify();
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function requestRefresh(): Promise<boolean> {
  let response: Response;
  try {
    response = await fetch(REFRESH_URL, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: "{}",
    });
  } catch {
    return false; // offline: keep the current state, callers show a network error
  }
  if (!response.ok) {
    clearAccessToken();
    return false;
  }
  const body = (await response.json()) as { access: string; access_expires_at: string };
  setAccessToken(body.access, body.access_expires_at);
  return true;
}

/** Get a fresh access token from the refresh cookie. Resolves false when there is no session. */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
    const run = locks ? locks.request("auth-refresh", requestRefresh) : requestRefresh();
    refreshing = Promise.resolve(run).finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

/** For tests. */
export function resetSessionForTests(): void {
  accessToken = null;
  accessExpiresAt = 0;
  refreshing = null;
  listeners.clear();
}
