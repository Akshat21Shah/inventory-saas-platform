// Synced from web/lib/i18n/numbers.ts by scripts/sync-from-web.mjs (npm run sync). Do not edit.
import { formatNumber } from "./format";

/** Arguments a message formats itself ({n, number}, {n, plural, …}): left as numbers. */
const OWN = /\{\s*([A-Za-z_]\w*)\s*,\s*(?:number|plural|selectordinal)\b/g;
const formattedBy = new Map<string, Set<string>>();

function ownArguments(message: string): Set<string> {
  let found = formattedBy.get(message);
  if (!found) {
    found = new Set([...message.matchAll(OWN)].map((match) => match[1]!));
    formattedBy.set(message, found);
  }
  return found;
}

/**
 * A message's values with every number formatted by the shared formatter (ADR-060 item 4): the
 * message would otherwise print 6029, not 6,029. Numbers a message formats itself (plural forms,
 * `{n, number}`) stay numbers: the locale formats them with the same Indian grouping.
 */
export function groupNumbers<V extends Record<string, unknown> | undefined>(
  message: string | undefined,
  values: V,
): V {
  if (!values) return values;
  const own = message ? ownArguments(message) : new Set<string>();
  let out: Record<string, unknown> | undefined;
  for (const [name, value] of Object.entries(values)) {
    if ((typeof value === "number" || typeof value === "bigint") && !own.has(name)) {
      out ??= { ...values };
      out[name] = formatNumber(value);
    }
  }
  return (out ?? values) as V;
}
