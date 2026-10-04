// Synced from web/lib/i18n/config.ts by scripts/sync-from-web.mjs (npm run sync). Do not edit.
import manifest from "./languages.json";

/**
 * The app's languages come from `languages.json` (ADR-060; the same file as the backend's, a test
 * keeps them equal): adding one is a manifest line and its messages file, no code. Which of them a
 * person may choose is the server's answer (`/auth/me` and the sign-in pages' branding).
 */
export interface LanguageInfo {
  code: string;
  name: string;
  native: string;
  script: string;
}

export const languages: readonly LanguageInfo[] = manifest.languages;
export const locales: readonly string[] = languages.map((language) => language.code);
export type Locale = string;
export const defaultLocale: Locale = manifest.default;
export const LOCALE_COOKIE = "NEXT_LOCALE";
export const TIME_ZONE = "Asia/Kolkata";

export function isLocale(value: string | undefined | null): value is Locale {
  return value !== undefined && value !== null && locales.includes(value);
}

/**
 * The Intl locale for a language: India, with the digits 0–9 (ADR-060 item 4). Marathi would
 * otherwise write numbers in Devanagari digits; counts in messages keep Indian grouping.
 */
export function intlLocale(code: Locale): string {
  return `${code}-IN-u-nu-latn`;
}

/** The language code of an Intl locale ("mr-IN-u-nu-latn" → "mr"). */
export function languageOf(locale: string): Locale {
  const code = locale.split("-")[0] ?? defaultLocale;
  return isLocale(code) ? code : defaultLocale;
}
