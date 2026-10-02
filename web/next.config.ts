import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./lib/i18n/request.ts");

// Same-origin API: the browser calls /api/* on its own host ({slug}.<domain>), Next proxies to
// Django and forwards X-Forwarded-Host so the backend can classify the host (ADR-020).
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

// Dev server only: "make lan" serves the app on <lan-ip>.nip.io so phones on the same Wi-Fi can
// use it. Next already allows localhost and its subdomains; any other platform domain is listed
// here (ignored by production builds).
const platformDomain = process.env.PLATFORM_DOMAIN ?? "localhost";
const allowedDevOrigins =
  platformDomain === "localhost" ? [] : [platformDomain, `*.${platformDomain}`];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  allowedDevOrigins,
  // No dev-only "N" indicator: every corner holds a control (the shop's bottom navigation, the
  // notification bell and account menu at the top). Build and runtime errors still show.
  devIndicators: false,
  reactStrictMode: true,
  // Django API paths end with "/" — never strip it on /api/* rewrites. Page URLs are normalised to
  // no trailing slash in proxy.ts instead.
  skipTrailingSlashRedirect: true,
  // A section's bare address opens its first tab. Redirected here, before anything renders: a page
  // that calls redirect() during a client-side navigation trips React's development-only
  // performance track ("'Page' cannot have a negative time stamp").
  async redirects() {
    return [
      { source: "/manage/purchasing", destination: "/manage/purchasing/orders", permanent: false },
      { source: "/manage/pricing", destination: "/manage/pricing/price-lists", permanent: false },
      { source: "/manage/settings", destination: "/manage/settings/business", permanent: false },
    ];
  },
  async rewrites() {
    return [
      // Order matters: keep the trailing slash Django expects (":path*" alone drops it).
      { source: "/api/:path*/", destination: `${apiInternalUrl}/api/:path*/` },
      { source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` },
      { source: "/health/:path*", destination: `${apiInternalUrl}/health/:path*` },
      // Live updates (WebSocket): same origin, so phones on "make lan" reach it through port 3000.
      { source: "/ws/:path*/", destination: `${apiInternalUrl}/ws/:path*/` },
    ];
  },
  async headers() {
    return [
      {
        source: "/shop/sw.js",
        headers: [
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/shop/" },
        ],
      },
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default withNextIntl(nextConfig);
