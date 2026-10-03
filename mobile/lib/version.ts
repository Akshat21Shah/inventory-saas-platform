/** App versions are three numbers ("1.2.0"); an unreadable one counts as the oldest. */
export function parseVersion(raw: string | null | undefined): [number, number, number] {
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec((raw ?? "").trim());
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : [0, 0, 0];
}

export function isOlder(version: string, than: string): boolean {
  const [a, b] = [parseVersion(version), parseVersion(than)];
  for (let i = 0; i < 3; i++) {
    if (a[i]! !== b[i]!) return a[i]! < b[i]!;
  }
  return false;
}
