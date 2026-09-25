// Forwarded headers are set here, never taken from the browser (ADR-032).
//
// Every request gets its X-Forwarded-For / -Host / -Proto (and Forwarded, X-Real-IP) removed and
// replaced with values derived from the connection. Only when the connecting peer is a trusted
// proxy (TRUSTED_PROXIES: the production load balancer) is its X-Forwarded-For consulted, and then
// only the rightmost address that is not itself a trusted proxy. Django trusts these headers only
// from this server (its own TRUSTED_PROXIES), so per-IP rate limits cannot be spoofed.
import { BlockList, isIP } from "node:net";

const STRIPPED = [
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-proto",
  "x-forwarded-port",
  "forwarded",
  "x-real-ip",
];

/** Strip the IPv4-mapped IPv6 prefix ("::ffff:10.0.0.1" -> "10.0.0.1"). */
export function normalizeAddress(address) {
  if (!address) return "";
  const trimmed = String(address).trim();
  return trimmed.startsWith("::ffff:") && isIP(trimmed.slice(7)) === 4 ? trimmed.slice(7) : trimmed;
}

/** Build a matcher from a comma-separated list of IPs and CIDRs ("10.0.0.0/8, 192.0.2.1"). */
export function createProxyMatcher(list) {
  const blocks = new BlockList();
  for (const raw of String(list ?? "").split(",")) {
    const entry = raw.trim();
    if (!entry) continue;
    const [address, prefix] = entry.split("/");
    const type = isIP(address) === 6 ? "ipv6" : "ipv4";
    if (!isIP(address)) throw new Error(`TRUSTED_PROXIES: not an address: ${entry}`);
    if (prefix === undefined) blocks.addAddress(address, type);
    else blocks.addSubnet(address, Number(prefix), type);
  }
  return (address) => {
    const ip = normalizeAddress(address);
    const version = isIP(ip);
    return version !== 0 && blocks.check(ip, version === 6 ? "ipv6" : "ipv4");
  };
}

function first(value) {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * Replace the request's forwarded headers in place.
 * @param {Record<string, string | string[] | undefined>} headers Node request headers (lower-case keys)
 * @param {{ remoteAddress?: string, encrypted?: boolean }} socket the connection
 * @param {(address: string) => boolean} isTrusted matcher from createProxyMatcher
 */
export function setForwardedHeaders(headers, socket, isTrusted) {
  const peer = normalizeAddress(socket.remoteAddress);
  const peerTrusted = isTrusted(peer);
  const upstreamFor = peerTrusted ? String(first(headers["x-forwarded-for"]) ?? "") : "";
  const upstreamProto = peerTrusted ? String(first(headers["x-forwarded-proto"]) ?? "") : "";
  for (const name of STRIPPED) delete headers[name];

  let client = peer;
  if (peerTrusted) {
    const chain = upstreamFor
      .split(",")
      .map(normalizeAddress)
      .filter((a) => isIP(a) !== 0);
    for (let i = chain.length - 1; i >= 0; i -= 1) {
      if (!isTrusted(chain[i])) {
        client = chain[i];
        break;
      }
    }
  }
  const proto = ["http", "https"].includes(upstreamProto)
    ? upstreamProto
    : socket.encrypted
      ? "https"
      : "http";
  if (client) headers["x-forwarded-for"] = client;
  if (headers.host) headers["x-forwarded-host"] = String(first(headers.host));
  headers["x-forwarded-proto"] = proto;
  return client;
}
