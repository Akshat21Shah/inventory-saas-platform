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
  // Keep the dev-only indicator clear of the retailer bottom navigation.
  devIndicators: { position: "top-right" },
  reactStrictMode: true,
  // Django API paths end with "/" — never strip it on /api/* rewrites. Page URLs are normalised to
  // no trailing slash in proxy.ts instead.
  skipTrailingSlashRedirect: true,
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
