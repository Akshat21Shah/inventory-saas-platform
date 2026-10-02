import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, TIME_ZONE, defaultLocale, intlLocale, isLocale } from "./config";

async function messagesFor(code: string): Promise<Record<string, unknown>> {
  try {
    return (await import(`../../messages/${code}.json`)).default;
  } catch {
    return (await import(`../../messages/${defaultLocale}.json`)).default;
  }
}

/**
 * The language of this request: the cookie the app sets from the person's saved language (or
 * their choice on a sign-in page), else English. The server decides which languages a person may
 * use; this only renders the one chosen (ADR-060).
 */
export default getRequestConfig(async () => {
  const cookie = (await cookies()).get(LOCALE_COOKIE)?.value;
  const code = isLocale(cookie) ? cookie : defaultLocale;
  return {
    locale: intlLocale(code),
    timeZone: TIME_ZONE,
    messages: await messagesFor(code),
  };
});
