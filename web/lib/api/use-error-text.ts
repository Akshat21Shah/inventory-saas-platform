"use client";

import { useMessages } from "next-intl";
import { useCallback, useMemo } from "react";

import { useTranslations } from "@/lib/i18n/translations";

import { ApiError, errorMessageKey } from "./errors";

/** Translated text for any error, and the server's per-field messages for form fields. */
export function useErrorText() {
  const t = useTranslations();
  const messages = useMessages() as { errors?: Record<string, string> };
  const known = useMemo(() => new Set(Object.keys(messages.errors ?? {})), [messages]);
  const message = useCallback((error: unknown) => t(errorMessageKey(error, known)), [t, known]);
  const fields = useCallback((error: unknown): Record<string, string> => {
    if (!(error instanceof ApiError)) return {};
    const raw = (error.details as { fields?: Record<string, unknown> }).fields ?? {};
    return Object.fromEntries(
      Object.entries(raw).map(([name, value]) => [
        name,
        Array.isArray(value) ? String(value[0]) : String(value),
      ]),
    );
  }, []);
  return { message, fields };
}
