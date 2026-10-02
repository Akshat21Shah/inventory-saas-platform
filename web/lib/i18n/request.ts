import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, TIME_ZONE, defaultLocale, intlLocale, isLocale } from "./config";

type Messages = { [key: string]: string | Messages };

/** A language's messages over the English ones, so a text not translated yet shows in English
 * rather than as its key (the tests keep every language complete; this is a safety net). */
function over(base: Messages, own: Messages): Messages {
  const out: Messages = { ...base };
  for (const [key, value] of Object.entries(own)) {
    const under = base[key];
    out[key] = typeof value === "object" && typeof under === "object" ? over(under, value) : value;
  }
  return out;
}

async function messagesFor(code: string): Promise<Messages> {
  const english = (await import(`../../messages/${defaultLocale}.json`)).default as Messages;
  if (code === defaultLocale) return english;
  try {
    return over(english, (await import(`../../messages/${code}.json`)).default as Messages);
  } catch {
    return english;
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
