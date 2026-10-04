/**
 * A web shop address as the app's screen, in the tab it belongs to. The shopping pages (an order,
 * a product, a category, search, notifications) are shared by every tab, so a link from outside
 * (WhatsApp, email, a push) or from the inbox needs its tab: an order opens in Orders (as after
 * placing one), a product, a category or a search in Catalog. The money pages are only in Account.
 */
const IN_TAB: [RegExp, string][] = [
  [/^\/shop\/orders\/[^/]+$/, "orders"],
  [/^\/shop\/products\/[^/]+$/, "catalog"],
  [/^\/shop\/catalog\/[^/]+$/, "catalog"],
  [/^\/shop\/search$/, "catalog"],
  [/^\/shop\/notifications$/, "home"],
];

export function appHref(path: string): string {
  const [pathname = "", query] = path.split("?");
  const tab = IN_TAB.find(([pattern]) => pattern.test(pathname))?.[1];
  if (!tab) return path;
  return `/shop/(tabs)/(${tab})${pathname.slice("/shop".length)}${query ? `?${query}` : ""}`;
}

/** The path of an address the phone opened the app with: a distributor's web address
 * (`https://sharma.…/shop/orders/1`), the app's own scheme (`shopapp://shop/payments/…`) or a
 * path. */
export function linkPath(url: string): string {
  const match = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]*)([^#]*)/i.exec(url);
  if (!match) return url;
  const [, scheme, host, rest] = match;
  if (/^https?$/i.test(scheme!)) return rest || "/";
  return `/${host}${rest}`; // shopapp://shop/payments/checkout/1 → /shop/payments/checkout/1
}
