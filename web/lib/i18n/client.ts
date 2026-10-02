"use client";

import { LOCALE_COOKIE, isLocale } from "./config";

/** The language on screen (the root layout writes it into <html lang>). */
export function screenLanguage(): string {
  return typeof document !== "undefined" ? document.documentElement.lang : "";
}

/**
 * Remember a language for the next renders (the server reads the cookie). Returns whether it
 * differs from the language on screen, so the caller refreshes the page's text.
 */
export function rememberLanguage(code: string | null | undefined): boolean {
  if (!isLocale(code) || typeof document === "undefined") return false;
  document.cookie = `${LOCALE_COOKIE}=${code}; path=/; max-age=31536000; SameSite=Lax`;
  return code !== screenLanguage();
}
