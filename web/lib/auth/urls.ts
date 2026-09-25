/** Moving a sign-in between hosts (ADR-020): handoff codes travel in the URL fragment, which is
 * never sent to any server or written to access logs. */

const SAFE_NEXT = /^\/(?!\/)[\w\-./?=&%#]*$/;

/** The platform domain seen from this browser host: "admin.x" → "x", "www.x" → "x", "slug.x" → "x". */
export function platformDomainFrom(hostname: string, tenantSlug?: string | null): string {
  if (tenantSlug && hostname.startsWith(`${tenantSlug}.`))
    return hostname.slice(tenantSlug.length + 1);
  for (const prefix of ["admin.", "www."]) {
    if (hostname.startsWith(prefix)) return hostname.slice(prefix.length);
  }
  return hostname;
}

export function tenantOrigin(slug: string, location: Location = window.location): string {
  const port = location.port ? `:${location.port}` : "";
  return `${location.protocol}//${slug}.${platformDomainFrom(location.hostname)}${port}`;
}

/** URL of the handoff page on the tenant subdomain, carrying the one-time code. */
export function handoffUrl(slug: string, code: string, next: string): string {
  const fragment = new URLSearchParams({ code, next }).toString();
  return `${tenantOrigin(slug)}/auth/handoff#${fragment}`;
}

/** Only same-site relative paths are accepted as a post-login destination. */
export function safeNext(value: string | null | undefined, fallback: string): string {
  return value && SAFE_NEXT.test(value) ? value : fallback;
}

export function homeFor(userType: string | undefined): string {
  if (userType === "PLATFORM") return "/platform";
  if (userType === "RETAILER") return "/shop";
  return "/manage";
}
