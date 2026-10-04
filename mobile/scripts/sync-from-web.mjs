#!/usr/bin/env node
/**
 * Copies what the app shares with the web (ADR-061 item 3), one way: the web is the source.
 *
 * - Plain TypeScript modules (formatting, number grouping, quantities, Idempotency-Keys, API
 *   errors, the brand palette) into `lib/shared/`.
 * - The translation namespaces the shop uses, per language, into `messages/web/<code>.json`.
 * - The design tokens from `web/app/globals.css` (colours converted from OKLCH to hex, which
 *   React Native understands) into `lib/shared/tokens.ts`.
 *
 * `npm run sync` writes them; `npm run sync -- --check` fails when any is stale (CI). Synced files
 * say so at the top and are never edited by hand.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(MOBILE, "..", "web");
const CHECK = process.argv.includes("--check");

const MODULES = {
  "lib/format.ts": "lib/shared/format.ts",
  "lib/i18n/numbers.ts": "lib/shared/numbers.ts",
  "lib/qty.ts": "lib/shared/qty.ts",
  "lib/idempotency.ts": "lib/shared/idempotency.ts",
  "lib/api/errors.ts": "lib/shared/errors.ts",
  "lib/theme/palette.ts": "lib/shared/palette.ts",
  "lib/i18n/config.ts": "lib/shared/i18n-config.ts",
  "lib/api/pagination.ts": "lib/shared/pagination.ts",
};
// JSON can't carry the "synced" header; it is copied as it is.
const DATA = { "lib/i18n/languages.json": "lib/shared/languages.json" };
// "@/lib/…" imports inside the copied modules, as paths inside lib/shared.
const IMPORTS = { "@/lib/format": "./format", "@/lib/idempotency": "./idempotency" };

export const NAMESPACES = [
  "shop",
  "notifications",
  "auth",
  "account",
  "common",
  "errors",
  "status",
  "offline",
  "billing",
  "orderStatus",
  "orderEvents",
  "shipmentStatus",
  "deliveryStatus",
  "paymentStatus",
  "refundStatus",
  "checkoutStatus",
  "returnRequestStatus",
  "shopReturnStatus",
  "connectionStatus",
  "providerMessages",
  "platformMessages",
  "suggestWord",
  "nav",
];
const LANGUAGES = ["en", "hi", "mr"];

const stale = [];

function write(relative, content) {
  const path = join(MOBILE, relative);
  const current = existsSync(path) ? readFileSync(path, "utf8") : null;
  if (current === content) return;
  if (CHECK) {
    stale.push(relative);
    return;
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
  console.log(`synced ${relative}`);
}

const header = (source) =>
  `// Synced from web/${source} by scripts/sync-from-web.mjs (npm run sync). Do not edit.\n`;

for (const [source, target] of Object.entries(MODULES)) {
  let code = readFileSync(join(WEB, source), "utf8");
  for (const [from, to] of Object.entries(IMPORTS)) code = code.replaceAll(`"${from}"`, `"${to}"`);
  if (/from "@\//.test(code)) throw new Error(`${source} imports a web path not mapped in IMPORTS`);
  write(target, header(source) + code);
}

for (const [source, target] of Object.entries(DATA)) {
  write(target, readFileSync(join(WEB, source), "utf8"));
}

for (const code of LANGUAGES) {
  const all = JSON.parse(readFileSync(join(WEB, "messages", `${code}.json`), "utf8"));
  const picked = {};
  for (const namespace of NAMESPACES) {
    if (!(namespace in all)) throw new Error(`web/messages/${code}.json has no "${namespace}"`);
    picked[namespace] = all[namespace];
  }
  write(`messages/web/${code}.json`, JSON.stringify(picked, null, 2) + "\n");
}

// --- Design tokens --------------------------------------------------------------------------------

/** OKLCH (CSS Color 4) → sRGB hex. */
function oklchToHex(l, c, h) {
  const rad = (h * Math.PI) / 180;
  const a = c * Math.cos(rad);
  const b = c * Math.sin(rad);
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;
  const [L, M, S] = [l_ ** 3, m_ ** 3, s_ ** 3];
  const linear = [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ];
  const gamma = (x) => (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055);
  return (
    "#" +
    linear
      .map((x) => Math.round(Math.min(1, Math.max(0, gamma(x))) * 255))
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("")
  );
}

const css = readFileSync(join(WEB, "app", "globals.css"), "utf8");
const root = css.match(/:root\s*\{([^}]*)\}/);
if (!root) throw new Error("web/app/globals.css has no :root block");
const colors = {};
let radius = null;
for (const [, name, value] of root[1].matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
  const oklch = value.match(/^oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)$/);
  if (oklch) colors[name] = oklchToHex(Number(oklch[1]), Number(oklch[2]), Number(oklch[3]));
  if (name === "radius") radius = Math.round(parseFloat(value) * 16);
}
const camel = (name) => name.replace(/-([a-z0-9])/g, (_, ch) => ch.toUpperCase());
const entries = Object.entries(colors)
  .filter(([name]) => !name.startsWith("sidebar") && !name.startsWith("chart"))
  .map(([name, hex]) => `  ${camel(name)}: "${hex}",`)
  .join("\n");
write(
  "lib/shared/tokens.ts",
  header("app/globals.css") +
    `/** The web's light theme, as hex. The brand colours are replaced at runtime by the distributor's. */\n` +
    `export const colors = {\n${entries}\n} as const;\n\n` +
    `export type ColorToken = keyof typeof colors;\n\n` +
    `/** The web's --radius in density-independent pixels (rem × 16). */\n` +
    `export const radius = ${radius};\n`,
);

if (CHECK && stale.length) {
  console.error(
    `Stale files synced from the web (run "npm run sync" in mobile/):\n  ${stale.join("\n  ")}`,
  );
  process.exit(1);
}
