"use client";

import { useTranslations as useNextIntlTranslations } from "next-intl";
import { useMemo } from "react";

import { groupNumbers } from "./numbers";

type Translator = ReturnType<typeof useNextIntlTranslations>;

/** A translator whose messages get every number they are given grouped (6,029; 1,23,456). */
export function withGroupedNumbers<T extends Translator>(t: T): T {
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
    )) as unknown as T;
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
  }) as T;
}

/**
 * next-intl's `useTranslations`, with every number given to a message formatted by the shared
 * formatter (Indian grouping, digits 0–9, every language; ADR-060). Use this, never next-intl's
 * own (a lint rule and a test keep it so).
 */
export const useTranslations = ((namespace?: string) => {
  const t = useNextIntlTranslations(namespace);
  return useMemo(() => withGroupedNumbers(t), [t]);
}) as typeof useNextIntlTranslations;
