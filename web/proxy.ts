import { NextResponse, type NextRequest } from "next/server";

import { classifyHost } from "@/lib/hosts";

const PLATFORM_DOMAIN = process.env.PLATFORM_DOMAIN ?? "localhost";

/**
 * Classifies the host once (ADR-019/020) and passes it to server components as request headers.
 * Area access rules (which host may open /platform, /manage, /shop) are enforced from Phase 1 when
 * sessions exist; the API enforces them regardless.
 */
export function proxy(request: NextRequest) {
  const host = request.headers.get("host") ?? "";
  const context = classifyHost(host, PLATFORM_DOMAIN);

  const { pathname } = request.nextUrl;
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return NextResponse.redirect(
      new URL(pathname.slice(0, -1) + request.nextUrl.search, request.url),
      308,
    );
  }

  if (context.kind === "ADMIN" && pathname === "/") {
    return NextResponse.redirect(new URL("/platform", request.url));
  }

  const headers = new Headers(request.headers);
  headers.set("x-host-kind", context.kind);
  if (context.tenantSlug) headers.set("x-tenant-slug", context.tenantSlug);
  else headers.delete("x-tenant-slug");
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: [
    "/((?!api|health|ws/|_next/static|_next/image|favicon.ico|shop/sw.js|shop/manifest.webmanifest|shop/icons).*)",
  ],
};
