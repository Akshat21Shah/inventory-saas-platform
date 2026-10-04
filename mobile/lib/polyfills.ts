/**
 * What Hermes lacks and the app needs:
 * - `crypto.getRandomValues` (Idempotency-Keys, the shared web code);
 * - `Intl.PluralRules` for plural messages ("1 item", "3 items", in every language), with what it
 *   builds on. Each polyfill installs itself only where the engine has none; only the app's
 *   languages' plural data is bundled (ADR-061 item 12).
 */
import "@formatjs/intl-getcanonicallocales/polyfill.js";
import "@formatjs/intl-locale/polyfill.js";
import "@formatjs/intl-pluralrules/polyfill.js";
import "@formatjs/intl-pluralrules/locale-data/en.js";
import "@formatjs/intl-pluralrules/locale-data/hi.js";
import "@formatjs/intl-pluralrules/locale-data/mr.js";

import { getRandomValues } from "expo-crypto";

const scope = globalThis as unknown as { crypto?: { getRandomValues?: unknown } };
if (typeof scope.crypto?.getRandomValues !== "function") {
  scope.crypto = { ...(scope.crypto ?? {}), getRandomValues };
}
