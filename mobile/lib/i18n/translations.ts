/**
 * use-intl's `useTranslations` (the core of the web's next-intl), with every number given to a
 * message formatted by the shared formatter: Indian grouping and the digits 0–9 in every
 * language (6,029; 1,23,456; ADR-060). The app's twin of `web/lib/i18n/translations.ts`.
 */
import { useMemo } from "react";
import { useTranslations as useIntlTranslations } from "use-intl";

import { groupNumbers } from "@/lib/shared/numbers";

type Translator = ReturnType<typeof useIntlTranslations>;

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
  const rich = (key: string, values?: Record<string, unknown>, formats?: unknown) =>
    (t.rich as unknown as (k: string, v?: unknown, f?: unknown) => unknown)(
      key,
      groupNumbers(raw(key), values),
      formats,
    );
  return Object.assign(grouped, { rich, raw: t.raw, has: t.has }) as T;
}

export const useTranslations = ((namespace?: string) => {
  const t = useIntlTranslations(namespace);
  return useMemo(() => withGroupedNumbers(t), [t]);
}) as typeof useIntlTranslations;
