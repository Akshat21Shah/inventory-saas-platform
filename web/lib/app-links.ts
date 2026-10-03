/**
 * Android App Links (ADR-061 item 8): the statement that lets the shop app open links to this
 * site's /shop pages. Served on every host (the generic domain and each distributor's subdomain),
 * so Android can verify `*.<domain>` whichever host it checks.
 *
 * Configured per deployment: `ANDROID_APP_ID` (the app's application ID) and
 * `ANDROID_APP_CERT_SHA256` (the signing certificates' SHA-256 fingerprints, comma-separated: the
 * Play App Signing key's from Play Console, and the upload key's). Unset: no statement (404).
 */
const APP_ID = /^[a-zA-Z][\w]*(\.[a-zA-Z][\w]*)+$/;
const FINGERPRINT = /^([0-9A-F]{2}:){31}[0-9A-F]{2}$/;

export interface AssetLink {
  relation: string[];
  target: { namespace: "android_app"; package_name: string; sha256_cert_fingerprints: string[] };
}

export function assetLinks(
  appId: string | undefined,
  fingerprints: string | undefined,
): AssetLink[] | null {
  const id = (appId ?? "").trim();
  const prints = (fingerprints ?? "")
    .split(",")
    .map((value) => value.trim().toUpperCase())
    .filter((value) => FINGERPRINT.test(value));
  if (!APP_ID.test(id) || prints.length === 0) return null;
  return [
    {
      relation: ["delegate_permission/common.handle_all_urls"],
      target: { namespace: "android_app", package_name: id, sha256_cert_fingerprints: prints },
    },
  ];
}
