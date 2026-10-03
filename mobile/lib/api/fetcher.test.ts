import * as SecureStore from "expo-secure-store";

import { startSession } from "@/lib/auth/session";
import { sessionEnded, updateRequired } from "@/lib/events";
import { ApiError } from "@/lib/shared/errors";

import { apiFetch } from "./fetcher";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const soon = () => new Date(Date.now() + 600_000).toISOString();

describe("apiFetch", () => {
  const fetchMock = jest.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    global.fetch = fetchMock;
  });

  it("sends the token, the language and the app's version", async () => {
    await startSession({ access: "A1", refresh: "R1", access_expires_at: soon() });
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    const result = await apiFetch<{ data: unknown }>("/api/v1/shop/home/");
    expect(result.data).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/v1/shop/home/");
    const headers = init.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer A1");
    expect(headers.get("X-App-Version")).toBe("1.0.0");
    expect(headers.get("Accept-Language")).toBe("en");
  });

  it("refreshes once on a 401 and keeps the rotated refresh token", async () => {
    await startSession({ access: "old", refresh: "R1", access_expires_at: soon() });
    fetchMock
      .mockResolvedValueOnce(
        json(401, { error: { code: "NOT_AUTHENTICATED", message: "", details: {} } }),
      )
      .mockResolvedValueOnce(json(200, { access: "new", access_expires_at: soon(), refresh: "R2" }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    await apiFetch("/api/v1/shop/home/");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ refresh: "R1" });
    expect((fetchMock.mock.calls[2][1].headers as Headers).get("Authorization")).toBe("Bearer new");
    expect(await SecureStore.getItemAsync("session.refresh")).toBe("R2");
  });

  it("ends the session when the refresh is refused", async () => {
    await startSession({ access: "old", refresh: "R1", access_expires_at: soon() });
    const ended = jest.fn();
    const stop = sessionEnded.listen(ended);
    fetchMock
      .mockResolvedValueOnce(
        json(401, { error: { code: "NOT_AUTHENTICATED", message: "", details: {} } }),
      )
      .mockResolvedValueOnce(
        json(401, { error: { code: "SESSION_EXPIRED", message: "", details: {} } }),
      );
    await expect(apiFetch("/api/v1/shop/home/")).rejects.toBeInstanceOf(ApiError);
    expect(ended).toHaveBeenCalled();
    expect(await SecureStore.getItemAsync("session.refresh")).toBeNull();
    stop();
  });

  it("asks for an update when the server refuses this version", async () => {
    const asked = jest.fn();
    const stop = updateRequired.listen(asked);
    fetchMock.mockResolvedValueOnce(
      json(426, {
        error: {
          code: "APP_UPDATE_REQUIRED",
          message: "Update",
          details: { min_version: "2.0.0" },
        },
      }),
    );
    await expect(apiFetch("/api/v1/app/config/")).rejects.toMatchObject({
      code: "APP_UPDATE_REQUIRED",
    });
    expect(asked).toHaveBeenCalled();
    stop();
  });

  it("turns a dropped connection into NETWORK_ERROR", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Network request failed"));
    await expect(apiFetch("/api/v1/shop/home/")).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      status: 0,
    });
  });
});
