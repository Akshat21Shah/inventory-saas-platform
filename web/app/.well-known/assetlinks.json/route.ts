import { assetLinks } from "@/lib/app-links";

/** Android App Links statement, on every host (ADR-061 item 8). JSON, no redirects. */
export function GET() {
  const links = assetLinks(process.env.ANDROID_APP_ID, process.env.ANDROID_APP_CERT_SHA256);
  if (links === null) return new Response("Not found", { status: 404 });
  return Response.json(links, { headers: { "Cache-Control": "public, max-age=3600" } });
}
