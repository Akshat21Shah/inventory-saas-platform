#!/usr/bin/env node
/**
 * Fails when a package with its own npm advisory is inside the app's JavaScript bundle (owner,
 * checkpoint review: advisories in build and test tools wait for Phase 10; none may ship).
 * Run after a release build: it reads the bundle's source map, which lists every file bundled.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const MAP =
  process.argv[2] ??
  "android/app/build/generated/sourcemaps/react/release/index.android.bundle.map";
let raw;
try {
  raw = execFileSync("npm", ["audit", "--json"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
} catch (error) {
  raw = error.stdout; // npm audit exits non-zero when it finds anything
}
const audit = JSON.parse(raw);
const own = Object.entries(audit.vulnerabilities ?? {})
  .filter(([, v]) => v.via.some((via) => typeof via === "object"))
  .map(([name]) => name);
const shipped = new Set();
for (const source of JSON.parse(readFileSync(MAP, "utf8")).sources) {
  const match = /node_modules\/((?:@[^/]+\/)?[^/]+)\//.exec(source);
  if (match) shipped.add(match[1]);
}
const inside = own.filter((name) => shipped.has(name));
console.log(`Advisories: ${own.join(", ") || "none"}; packages in the bundle: ${shipped.size}.`);
if (inside.length) {
  console.error(`Shipped inside the app: ${inside.join(", ")}`);
  process.exit(1);
}
console.log("None of them ships inside the app.");
