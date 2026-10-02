import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// The ICU parser next-intl itself uses (a dependency of next-intl), to compare message shapes.
import { parse, TYPE, type MessageFormatElement } from "@formatjs/icu-messageformat-parser";
import { describe, expect, it } from "vitest";

import manifest from "@/lib/i18n/languages.json";
import en from "@/messages/en.json";

type Messages = { [key: string]: string | Messages };

function leaves(messages: Messages, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(messages)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(path, value);
    else for (const [k, v] of leaves(value, path)) out.set(k, v);
  }
  return out;
}

/** What a translation must keep from the English: argument names and types, plural and select
 * options, rich-text tags. The words around them are free. */
function shape(elements: MessageFormatElement[], out: string[] = []): string[] {
  for (const el of elements) {
    if (el.type === TYPE.argument || el.type === TYPE.number || el.type === TYPE.date)
      out.push(`${el.type}:${el.value}`);
    if (el.type === TYPE.plural || el.type === TYPE.select) {
      const options = Object.keys(el.options).sort();
      out.push(`${el.type}:${el.value}:${options.join("|")}`);
      for (const option of options) shape(el.options[option]!.value, out);
    }
    if (el.type === TYPE.tag) {
      out.push(`tag:${el.value}`);
      shape(el.children, out);
    }
  }
  return out.sort();
}

const english = leaves(en as Messages);
const others = manifest.languages.filter((l) => l.code !== manifest.default);

describe("every language has every screen text (ADR-060)", () => {
  it("lists the languages from the shared manifest", () => {
    expect(others.map((l) => l.code)).toEqual(["hi", "mr"]);
  });

  for (const language of others) {
    const file = resolve(__dirname, `../messages/${language.code}.json`);
    const own = leaves(JSON.parse(readFileSync(file, "utf8")) as Messages);

    it(`${language.name}: the same keys as English`, () => {
      expect([...english.keys()].filter((k) => !own.has(k))).toEqual([]);
      expect([...own.keys()].filter((k) => !english.has(k))).toEqual([]);
    });

    it(`${language.name}: the same placeholders, plurals and tags, and nothing left empty`, () => {
      const wrong: string[] = [];
      for (const [key, text] of own) {
        const source = english.get(key);
        if (source === undefined) continue;
        if (!text.trim()) {
          wrong.push(`${key}: empty`);
          continue;
        }
        try {
          if (shape(parse(text)).join() !== shape(parse(source)).join()) wrong.push(key);
        } catch (error) {
          wrong.push(`${key}: ${String(error)}`);
        }
      }
      expect(wrong).toEqual([]);
    });

    it(`${language.name}: plurals always have an "other" form`, () => {
      const missing = [...own].filter(
        ([, text]) => /, plural,/.test(text) && !/other \{/.test(text),
      );
      expect(missing.map(([key]) => key)).toEqual([]);
    });
  }
});
