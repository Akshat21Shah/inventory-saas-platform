import type { PublicBranding } from "@/lib/api/generated/model";

/**
 * Pre-login branding for a tenant subdomain (server side). Not cached: availability and branding
 * must change on the next page load (a tenant activated by its owner must not look unavailable
 * for a minute). The request is two indexed lookups, deduplicated per render by the layout.
 */
export async function fetchPublicBranding(slug: string): Promise<PublicBranding | null> {
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(
      `${base}/api/v1/public/tenants/${encodeURIComponent(slug)}/branding/`,
      { cache: "no-store" },
    );
    if (!response.ok) return null;
    return (await response.json()) as PublicBranding;
  } catch {
    return null;
  }
}
