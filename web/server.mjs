// Web server: Next.js behind our own forwarded-header handling (ADR-032). `npm run dev` / `start`.
import { createServer } from "node:http";

import next from "next";

import { createProxyMatcher, setForwardedHeaders } from "./server/forwarded.mjs";

const dev = process.env.NODE_ENV !== "production";
const hostname = process.env.WEB_HOST ?? "0.0.0.0";
const port = Number(process.env.PORT ?? 3000);
// Proxies in front of this server (production load balancer). Empty: browsers connect directly.
// TODO(verify): production load balancer addresses and behaviour (PROGRESS pre-production #3).
const isTrusted = createProxyMatcher(process.env.TRUSTED_PROXIES ?? "");

const app = next({ dev, hostname, port, ...(dev ? { turbopack: true } : {}) });
await app.prepare();
const handle = app.getRequestHandler();
const upgrade = app.getUpgradeHandler();

const server = createServer((req, res) => {
  setForwardedHeaders(req.headers, req.socket, isTrusted);
  void handle(req, res);
});
server.on("upgrade", (req, socket, head) => {
  setForwardedHeaders(req.headers, req.socket, isTrusted);
  void upgrade(req, socket, head);
});
server.listen(port, hostname, () => {
  console.log(`> Web ready on http://${hostname}:${port} (${dev ? "development" : "production"})`);
});
