import type { PublicBranding } from "@/lib/api/generated/model";

/** Pre-login branding for a tenant subdomain (server side; cached for a minute). */
export async function fetchPublicBranding(slug: string): Promise<PublicBranding | null> {
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(
      `${base}/api/v1/public/tenants/${encodeURIComponent(slug)}/branding/`,
      {
        next: { revalidate: 60 },
      },
    );
    if (!response.ok) return null;
    return (await response.json()) as PublicBranding;
  } catch {
    return null;
  }
}
