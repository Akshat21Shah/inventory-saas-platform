/**
 * Small files in the app's own storage (never shared, removed with the app): the saved copy of
 * what the shop has seen, its profile and the cart changes waiting for a connection. Nothing secret
 * (the session stays in secure storage). Signing out removes them all.
 */
import { Directory, File, Paths } from "expo-file-system";

const folder = () => new Directory(Paths.document, "saved");

function file(key: string): File {
  const dir = folder();
  if (!dir.exists) dir.create({ idempotent: true });
  return new File(dir, `${key}.json`);
}

/** The async storage TanStack's persister and the app expect. */
export const fileStore = {
  async getItem(key: string): Promise<string | null> {
    const f = file(key);
    return f.exists ? f.text() : null;
  },
  async setItem(key: string, value: string): Promise<void> {
    file(key).write(value);
  },
  async removeItem(key: string): Promise<void> {
    const f = file(key);
    if (f.exists) f.delete();
  },
};

/** Sign-out: nothing of this shop stays on the phone. */
export async function clearFileStore(): Promise<void> {
  const dir = folder();
  if (dir.exists) dir.delete();
}
