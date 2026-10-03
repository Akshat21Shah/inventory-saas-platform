/**
 * The app's language (ADR-060, ADR-061 item 4): before sign-in the phone's language if the app
 * has it, else English, or what the person picked on the sign-in screen; after sign-in the
 * person's saved language (`/auth/me`). Kept on the phone so the next start opens in it.
 */
import { getLocales } from "expo-localization";
import * as SecureStore from "expo-secure-store";

import { defaultLocale, isLocale, type Locale } from "@/lib/shared/i18n-config";

const KEY = "app.language";
let language: Locale = defaultLocale;
let changes = 0; // setLanguage calls, so a slower read of the saved one can't undo a newer choice
const listeners = new Set<(code: Locale) => void>();

export function currentLanguage(): Locale {
  return language;
}

export function phoneLanguage(): Locale {
  const code = getLocales()[0]?.languageCode ?? defaultLocale;
  return isLocale(code) ? code : defaultLocale;
}

/** On start: the saved language, else the phone's (screens re-render when it differs). */
export async function loadLanguage(): Promise<Locale> {
  const before = changes;
  const saved = await SecureStore.getItemAsync(KEY);
  // The person's language from the server (or a pick on the sign-in screen) came first.
  if (changes !== before) return language;
  const found = isLocale(saved) ? saved : phoneLanguage();
  if (found !== language) {
    language = found;
    listeners.forEach((listener) => listener(found));
  }
  return language;
}

export async function setLanguage(code: Locale): Promise<void> {
  if (!isLocale(code)) return;
  changes += 1;
  if (code === language) return;
  language = code;
  await SecureStore.setItemAsync(KEY, code);
  listeners.forEach((listener) => listener(code));
}

export function onLanguageChange(listener: (code: Locale) => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
