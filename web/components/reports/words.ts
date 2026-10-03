"use client";

import { useTranslations } from "@/lib/i18n/translations";
import { useMemo } from "react";

/**
 * A report's words from the messages (`reports.catalogue`, `.filters`, `.choices`, `.groups`),
 * with the server's own label when one is missing. The server names its reports and columns (the
 * same words head the Excel files); the messages translate them, and a backend test keeps them
 * complete (`test_catalogue_i18n.py`).
 */
export function useReportWords() {
  const t = useTranslations("reports");
  return useMemo(() => {
    const pick = (key: string, fallback: string) => (t.has(key) ? t(key) : fallback);
    return {
      title: (code: string, fallback: string) => pick(`catalogue.${code}.title`, fallback),
      description: (code: string, fallback: string) =>
        pick(`catalogue.${code}.description`, fallback),
      column: (code: string, key: string, fallback: string) =>
        pick(`catalogue.${code}.columns.${key}`, fallback),
      filter: (key: string, fallback: string) => pick(`filters.${key}`, fallback),
      choice: (key: string, value: string) => pick(`choices.${key}.${value}`, value),
      group: (group: string) => pick(`groups.${group}`, group),
    };
  }, [t]);
}

export type ReportWords = ReturnType<typeof useReportWords>;
