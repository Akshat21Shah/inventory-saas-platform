export function normalizeAddress(address: string | undefined | null): string;
export function createProxyMatcher(list: string | undefined | null): (address: string) => boolean;
export function setForwardedHeaders(
  headers: Record<string, string | string[] | undefined>,
  socket: { remoteAddress?: string; encrypted?: boolean },
  isTrusted: (address: string) => boolean,
): string;
