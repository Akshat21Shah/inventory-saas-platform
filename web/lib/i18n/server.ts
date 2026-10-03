import { getTranslations as getNextIntlTranslations } from "next-intl/server";

import { groupNumbers } from "./numbers";

type Translator = Awaited<ReturnType<typeof getNextIntlTranslations>>;

function withGroupedNumbers(t: Translator): Translator {
  const raw = (key: string): string | undefined => {
    try {
      const found: unknown = t.raw(key);
      return typeof found === "string" ? found : undefined;
    } catch {
      return undefined;
    }
  };
  const grouped = ((key: string, values?: Record<string, unknown>, formats?: unknown) =>
    (t as unknown as (k: string, v?: unknown, f?: unknown) => string)(
      key,
      groupNumbers(raw(key), values),
      formats,
    )) as unknown as Translator;
  const call =
    (method: "rich" | "markup") =>
    (key: string, values?: Record<string, unknown>, formats?: unknown) =>
      (t[method] as unknown as (k: string, v?: unknown, f?: unknown) => unknown)(
        key,
        groupNumbers(raw(key), values),
        formats,
      );
  return Object.assign(grouped, {
    rich: call("rich"),
    markup: call("markup"),
    raw: t.raw,
    has: t.has,
  }) as Translator;
}

/** next-intl's `getTranslations` (server components, metadata), numbers grouped (ADR-060). */
export const getTranslations = (async (...args: Parameters<typeof getNextIntlTranslations>) =>
  withGroupedNumbers(await getNextIntlTranslations(...args))) as typeof getNextIntlTranslations;
