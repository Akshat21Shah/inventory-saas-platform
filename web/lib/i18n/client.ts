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

const PICKED = "language-picked";

/** Whether this browser has a language remembered already. */
export function hasLanguageCookie(): boolean {
  return typeof document !== "undefined" && document.cookie.includes(`${LOCALE_COOKIE}=`);
}

/**
 * A language the person picked before signing in (a sign-in or invite page): shown at once, and
 * saved to their profile when they sign in (ADR-060 item 2). Returns whether the screen changes.
 */
export function pickLanguage(code: string): boolean {
  try {
    sessionStorage.setItem(PICKED, code);
  } catch {
    // Storage may be blocked: the cookie still shows it until they sign in.
  }
  return rememberLanguage(code);
}

/** The language picked before signing in, if any (left in place). */
export function pickedLanguage(): string | null {
  try {
    return sessionStorage.getItem(PICKED);
  } catch {
    return null;
  }
}

/** The language picked before signing in, once: it is then saved to the profile. */
export function takePickedLanguage(): string | null {
  const picked = pickedLanguage();
  try {
    sessionStorage.removeItem(PICKED);
  } catch {
    // Nothing to forget.
  }
  return picked;
}
