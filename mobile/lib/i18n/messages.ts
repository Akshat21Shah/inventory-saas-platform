/**
 * Every text the app shows: the shop's texts from the web (`messages/web`, synced) and the app's
 * own (`messages/app`, under the `app` namespace), per language. A text not translated yet shows
 * in English, never as its key (the checks keep every language complete; this is a safety net).
 */
import appEn from "@/messages/app/en.json";
import appHi from "@/messages/app/hi.json";
import appMr from "@/messages/app/mr.json";
import webEn from "@/messages/web/en.json";
import webHi from "@/messages/web/hi.json";
import webMr from "@/messages/web/mr.json";

export type Messages = { [key: string]: string | Messages };

function over(base: Messages, own: Messages): Messages {
  const out: Messages = { ...base };
  for (const [key, value] of Object.entries(own)) {
    const under = base[key];
    out[key] = typeof value === "object" && typeof under === "object" ? over(under, value) : value;
  }
  return out;
}

const english: Messages = { ...(webEn as Messages), app: appEn as Messages };
const own: Record<string, Messages> = {
  hi: { ...(webHi as Messages), app: appHi as Messages },
  mr: { ...(webMr as Messages), app: appMr as Messages },
};
const cache = new Map<string, Messages>();

export function messagesFor(code: string): Messages {
  if (code === "en") return english;
  let found = cache.get(code);
  if (!found) {
    found = own[code] ? over(english, own[code]) : english;
    cache.set(code, found);
  }
  return found;
}
