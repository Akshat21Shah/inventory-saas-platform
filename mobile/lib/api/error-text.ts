/**
 * Translated text for any error, and the server's per-field messages for form fields: the app's
 * twin of `web/lib/api/use-error-text.ts`. People never see raw technical errors.
 */
import { useCallback, useMemo } from "react";
import { useMessages } from "use-intl";

import { useTranslations } from "@/lib/i18n/translations";
import { ApiError, errorMessageKey } from "@/lib/shared/errors";

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
  return useMemo(() => ({ message, fields }), [message, fields]);
}
