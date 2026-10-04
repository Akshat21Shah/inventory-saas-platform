/**
 * Every text the app's code asks for is in the English texts (ADR-061): a mistyped key would
 * show on the screen as the key itself. Reads the code: `const t = useTranslations("ns")`, then
 * `t("key")`, `t.rich("key")` and `t.raw("key")` up to the next `useTranslations` of that name. A
 * key built while the app runs (`t(`status.${code}`)`) needs its fixed start to be a group of
 * texts. The Hindi and Marathi have the same keys (messages.test.ts and the web's checks).
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { type Messages, messagesFor } from "./messages";

const ROOT = join(__dirname, "..", "..");
const SKIP = new Set(["node_modules", "generated"]);

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return SKIP.has(entry.name) ? [] : sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

const english = messagesFor("en");

function lookup(key: string): string | Messages | undefined {
  return key
    .split(".")
    .reduce<string | Messages | undefined>(
      (node, part) => (typeof node === "object" ? node[part] : undefined),
      english,
    );
}

type Use = { file: string; key: string; built: boolean };

/** The keys asked for in one file, with their namespaces. */
function usesIn(file: string): Use[] {
  const code = readFileSync(file, "utf8");
  const declared = [...code.matchAll(/const (\w+) = useTranslations\(\s*(?:"([^"]*)")?\s*\)/g)];
  const uses: Use[] = [];
  for (const name of new Set(declared.map((d) => d[1]!))) {
    const mine = declared.filter((d) => d[1] === name);
    const call = new RegExp(
      String.raw`(?<![\w.])${name}(?:\.rich|\.raw)?\(\s*(["\x60])(.*?)\1`,
      "g",
    );
    for (const found of code.matchAll(call)) {
      // The closest `useTranslations` of this name above the call gives its namespace.
      const owner = mine.filter((d) => d.index! < found.index!).at(-1);
      if (!owner) continue; // a translator passed in as a parameter
      const namespace = owner[2] ?? "";
      const literal = found[2]!;
      const built = found[1] === "`" && literal.includes("${");
      const key = built ? literal.slice(0, literal.indexOf("${")).replace(/\.$/, "") : literal;
      if (built && !key) continue;
      uses.push({
        file: relative(ROOT, file),
        key: [namespace, key].filter(Boolean).join("."),
        built,
      });
    }
  }
  return uses;
}

const uses = ["app", "components", "lib"]
  .flatMap((dir) => sources(join(ROOT, dir)))
  .flatMap(usesIn);

describe("the app's texts", () => {
  it("are read from the code", () => {
    expect(uses.length).toBeGreaterThan(300);
  });

  it("include every key the code asks for", () => {
    const missing = uses
      .filter(({ key, built }) =>
        built ? typeof lookup(key) !== "object" : typeof lookup(key) !== "string",
      )
      .map(({ file, key }) => `${file}: ${key}`);
    expect(missing).toEqual([]);
  });
});
