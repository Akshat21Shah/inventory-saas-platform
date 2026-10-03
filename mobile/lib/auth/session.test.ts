import * as SecureStore from "expo-secure-store";

import { hasStoredSession, restoreSession } from "./session";

const mockFetch = jest.fn();
beforeEach(() => {
  mockFetch.mockReset();
  global.fetch = mockFetch as unknown as typeof fetch;
});

describe("Starting the app", () => {
  it("carries on with the saved session when there's no connection", async () => {
    await SecureStore.setItemAsync("session.refresh", "refresh-1");
    mockFetch.mockRejectedValue(new TypeError("Network request failed"));
    expect(await restoreSession()).toBe(true);
    expect(await hasStoredSession()).toBe(true);
  });

  it("signs out when the server says the session is over", async () => {
    await SecureStore.setItemAsync("session.refresh", "refresh-1");
    mockFetch.mockResolvedValue(new Response("{}", { status: 401 }));
    expect(await restoreSession()).toBe(false);
    expect(await hasStoredSession()).toBe(false);
  });

  it("has nothing to restore without a saved session", async () => {
    expect(await restoreSession()).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
