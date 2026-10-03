import { render, screen } from "@testing-library/react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { intlLocale } from "./config";
import { groupNumbers } from "./numbers";
import { useTranslations } from "./translations";

/**
 * Every number inside a message goes through the shared formatter (ADR-060 item 4, owner at the
 * 11a final review): Indian grouping and the digits 0–9 in all three languages. The source check
 * fails on a screen that formats a number any other way.
 */
const MESSAGES = {
  rows: {
    simple: "{count} rows checked",
    plural: "{count, plural, one {# row} other {# rows}} checked",
    number: "{done, number} of {total, number}",
    rich: "<b>{count}</b> shops",
  },
};

function Rows() {
  const t = useTranslations("rows");
  return (
    <ul>
      <li>{t("simple", { count: 123456 })}</li>
      <li>{t("plural", { count: 123456 })}</li>
      <li>{t("number", { done: 6029, total: 123456 })}</li>
      <li>{t.rich("rich", { count: 6029, b: (chunks) => <b>{chunks}</b> })}</li>
    </ul>
  );
}

describe("numbers in messages", () => {
  it.each(["en", "hi", "mr"])("are grouped the Indian way in %s", (language) => {
    render(
      <NextIntlClientProvider
        locale={intlLocale(language)}
        messages={MESSAGES}
        timeZone="Asia/Kolkata"
      >
        <Rows />
      </NextIntlClientProvider>,
    );
    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items).toEqual([
      "1,23,456 rows checked",
      "1,23,456 rows checked",
      "6,029 of 1,23,456",
      "6,029 shops",
    ]);
  });

  it("formats only the numbers a message doesn't format itself", () => {
    expect(groupNumbers("{n} left", { n: 6029, name: "Ganesh" })).toEqual({
      n: "6,029",
      name: "Ganesh",
    });
    const plural = { count: 6029 };
    expect(groupNumbers("{count, plural, other {# rows}}", plural)).toBe(plural);
    expect(groupNumbers("{code} and {n}", { code: "411001", n: 12345678 })).toEqual({
      code: "411001",
      n: "1,23,45,678",
    });
    expect(groupNumbers(undefined, undefined)).toBeUndefined();
  });
});

const ROOT = join(__dirname, "..", "..");
const ALLOWED = new Set(["lib/format.ts", "lib/i18n/translations.ts", "lib/i18n/server.ts"]);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "generated" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

describe("the screens' code", () => {
  it("formats numbers only through the shared formatter", () => {
    const wrong: string[] = [];
    for (const path of ["app", "components", "lib"].flatMap((dir) => sources(join(ROOT, dir)))) {
      const file = relative(ROOT, path);
      if (ALLOWED.has(file)) continue;
      const text = readFileSync(path, "utf-8");
      const checks: [RegExp, string][] = [
        [
          /import \{[^}]*\buseTranslations\b[^}]*\} from "next-intl"/,
          "next-intl's useTranslations",
        ],
        [/import \{[^}]*\buseFormatter\b[^}]*\} from "next-intl"/, "next-intl's useFormatter"],
        [/import \{[^}]*\bgetTranslations\b[^}]*\} from "next-intl\/server"/, "getTranslations"],
        [/\.toLocaleString\(/, "toLocaleString"],
        [/Intl\.NumberFormat/, "Intl.NumberFormat"],
      ];
      for (const [pattern, what] of checks) if (pattern.test(text)) wrong.push(`${file}: ${what}`);
    }
    expect(wrong).toEqual([]);
  });
});
