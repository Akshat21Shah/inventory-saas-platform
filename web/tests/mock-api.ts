import { vi } from "vitest";

export type Handler = (body: unknown, url: URL) => [number, unknown];

export interface ApiCall {
  method: string;
  path: string;
  url: URL;
  body: unknown;
}

/**
 * Stub `fetch` with routes keyed by "METHOD /path/" (the query string is ignored; GET may be
 * omitted). Unknown routes answer 404 so a missing mock is obvious. Returns the recorded calls.
 */
export function mockApi(routes: Record<string, Handler>): ApiCall[] {
  const calls: ApiCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input, "http://localhost");
      const method = (init.method ?? "GET").toUpperCase();
      let body: unknown = init.body;
      if (typeof init.body === "string") body = JSON.parse(init.body);
      calls.push({ method, path: url.pathname, url, body });
      const handler =
        routes[`${method} ${url.pathname}`] ??
        (method === "GET" ? routes[url.pathname] : undefined);
      const [status, payload] = handler
        ? handler(body, url)
        : [404, { error: { code: "NOT_FOUND", message: "", details: {} } }];
      return new Response(payload === undefined ? null : JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}
