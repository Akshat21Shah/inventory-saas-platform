/** Host classification — mirrors backend `common/hosts.py` (ADR-019/020). */

export type HostKind = "ADMIN" | "TENANT" | "GENERIC" | "UNKNOWN";
export interface HostContext {
  kind: HostKind;
  tenantSlug: string | null;
}

const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$/;
const RESERVED = new Set(["admin", "www", "api", "app", "static", "media", "mail"]);

export function classifyHost(host: string, platformDomain: string): HostContext {
  const domain = platformDomain.toLowerCase();
  const hostname = (host.split(":")[0] ?? "").toLowerCase().replace(/\.$/, "");
  if (hostname === domain || hostname === `www.${domain}`)
    return { kind: "GENERIC", tenantSlug: null };
  if (hostname === `admin.${domain}`) return { kind: "ADMIN", tenantSlug: null };
  const suffix = `.${domain}`;
  if (hostname.endsWith(suffix)) {
    const label = hostname.slice(0, -suffix.length);
    if (!label.includes(".") && !RESERVED.has(label) && SLUG_RE.test(label)) {
      return { kind: "TENANT", tenantSlug: label };
    }
  }
  return { kind: "UNKNOWN", tenantSlug: null };
}
