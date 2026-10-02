"use client";

import { useTranslations } from "next-intl";

/** The GST provider's error codes with a line of their own (others take their context's line). */
const CODES = [
  "CREDENTIALS_NOT_READY",
  "NUMBER_USED",
  "INVOICE_CANCELLED",
  "AUTH_FAILED",
  "INVALID_GSTIN",
  "DUPLICATE",
  "PORTAL_DOWN",
  "TIMEOUT",
  "CANCEL_NOT_ALLOWED",
] as const;
/** Failures of our own: the line says it all, there are no provider's words to show. */
const OURS = new Set<string>(["CREDENTIALS_NOT_READY", "NUMBER_USED", "INVOICE_CANCELLED"]);

export type GstContext = "einvoice" | "ewaybill" | "update" | "login";

/**
 * What a GST failure shows (ADR-060, owner): a translated line saying what failed, from its error
 * code or else where it happened, and the provider's own English words under it.
 */
export function useGstFailure() {
  const t = useTranslations("compliance.provider");
  return (
    context: GstContext,
    code: string | null | undefined,
    message: string | null | undefined,
  ) => {
    const known = (CODES as readonly string[]).includes(code ?? "");
    return {
      line: known ? t(`codes.${code as (typeof CODES)[number]}`) : t(context),
      message: code && OURS.has(code) ? "" : (message ?? ""),
    };
  };
}
