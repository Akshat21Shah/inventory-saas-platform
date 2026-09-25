import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION_ENDED_EVENT, apiFetch } from "@/lib/api/fetcher";

import {
  accessTokenStale,
  getAccessToken,
  refreshSession,
  resetSessionForTests,
  setAccessToken,
} from "./session";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const future = () => new Date(Date.now() + 10 * 60_000).toISOString();

describe("session (ADR-025)", () => {
  beforeEach(() => resetSessionForTests());
  afterEach(() => vi.unstubAllGlobals());

  it("refreshes once for concurrent callers and stores the new token in memory", async () => {
    const fetchMock = vi.fn(async () =>
      json(200, { access: "new-token", access_expires_at: future() }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(results).toEqual([true, true, true]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).get("X-Requested-With")).toBe("fetch");
    expect(init.credentials).toBe("include");
    expect(getAccessToken()).toBe("new-token");
    expect(accessTokenStale()).toBe(false);
  });

  it("clears the token when the refresh cookie is no longer valid", async () => {
    setAccessToken("old", future());
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(401, { error: { code: "SESSION_EXPIRED", message: "", details: {} } }),
      ),
    );
    expect(await refreshSession()).toBe(false);
    expect(getAccessToken()).toBeNull();
  });
});

describe("apiFetch", () => {
  beforeEach(() => resetSessionForTests());
  afterEach(() => vi.unstubAllGlobals());

  it("sends the bearer token, refreshes once on 401 and retries", async () => {
    setAccessToken("expired-by-server", future());
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        const auth = new Headers(init.headers).get("Authorization");
        calls.push(`${url} ${auth ?? ""}`);
        if (url.endsWith("/token/refresh/"))
          return json(200, { access: "fresh", access_expires_at: future() });
        return auth === "Bearer fresh"
          ? json(200, { ok: true })
          : json(401, { error: { code: "AUTHENTICATION_FAILED", message: "", details: {} } });
      }),
    );
    const response = await apiFetch<{ data: { ok: boolean } }>("/api/v1/auth/me/");
    expect(response.data.ok).toBe(true);
    expect(calls).toEqual([
      "/api/v1/auth/me/ Bearer expired-by-server",
      "/api/v1/auth/token/refresh/ ",
      "/api/v1/auth/me/ Bearer fresh",
    ]);
  });

  it("announces the end of the session when refreshing fails", async () => {
    setAccessToken("t", future());
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(401, { error: { code: "SESSION_EXPIRED", message: "", details: {} } }),
      ),
    );
    const ended = vi.fn();
    window.addEventListener(SESSION_ENDED_EVENT, ended);
    await expect(apiFetch("/api/v1/auth/me/")).rejects.toMatchObject({ code: "SESSION_EXPIRED" });
    expect(ended).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_ENDED_EVENT, ended);
  });

  it("does not try to refresh when there was no session", async () => {
    const fetchMock = vi.fn(async () =>
      json(401, { error: { code: "NOT_AUTHENTICATED", message: "", details: {} } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/api/v1/auth/me/")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
