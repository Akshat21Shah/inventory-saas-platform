import { describe, expect, it, vi, afterEach } from "vitest";

import { ApiError, errorMessageKey } from "./errors";
import { apiFetch } from "./fetcher";

const KNOWN = new Set(["CREDIT_LIMIT_EXCEEDED", "NETWORK_ERROR", "UNKNOWN_ERROR"]);

describe("errorMessageKey", () => {
  it("maps known API codes, network errors and unknown failures to i18n keys", () => {
    const apiError = new ApiError(422, {
      code: "CREDIT_LIMIT_EXCEEDED",
      message: "raw",
      details: {},
    });
    expect(errorMessageKey(apiError, KNOWN)).toBe("errors.CREDIT_LIMIT_EXCEEDED");
    expect(errorMessageKey(new TypeError("fetch failed"), KNOWN)).toBe("errors.NETWORK_ERROR");
    expect(
      errorMessageKey(new ApiError(400, { code: "NEW_CODE", message: "", details: {} }), KNOWN),
    ).toBe("errors.UNKNOWN_ERROR");
  });
});

describe("apiFetch", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns data, status and headers on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })),
    );
    const result = await apiFetch<{ data: unknown; status: number }>("/api/v1/meta/");
    expect(result.data).toEqual({ ok: true });
    expect(result.status).toBe(200);
  });

  it("throws ApiError carrying the envelope code", async () => {
    const body = { error: { code: "PERMISSION_DENIED", message: "no", details: {} } };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(body), { status: 403 })),
    );
    await expect(apiFetch("/api/v1/x/")).rejects.toMatchObject({
      status: 403,
      code: "PERMISSION_DENIED",
    });
  });

  it("turns network failures into NETWORK_ERROR", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("offline"))),
    );
    await expect(apiFetch("/api/v1/x/")).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("sends JSON content type and credentials", async () => {
    const spy = vi.fn(async () => new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/api/v1/x/", { method: "POST", body: JSON.stringify({ a: 1 }) });
    const init = (spy.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.credentials).toBe("include");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  });
});
