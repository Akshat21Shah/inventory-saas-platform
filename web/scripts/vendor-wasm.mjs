// Copies the barcode reader's WebAssembly file into public/vendor, so phones load it from our own
// server (never a third-party CDN). Runs before `dev` and `build`; the copy is git-ignored.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const entry = require.resolve("zxing-wasm/reader");
const root = entry.slice(0, entry.lastIndexOf("/zxing-wasm/") + "/zxing-wasm".length);
const source = join(root, "dist", "reader", "zxing_reader.wasm");
const target = new URL("../public/vendor/zxing_reader.wasm", import.meta.url);
mkdirSync(new URL("../public/vendor/", import.meta.url), { recursive: true });
copyFileSync(source, target);
