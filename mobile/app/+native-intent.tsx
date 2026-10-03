import { appHref, linkPath } from "@/lib/app-href";

/** Links that open the app (App Links, the app's scheme, a tapped push): each to its screen in the
 * tab it belongs to. */
export function redirectSystemPath({ path }: { path: string; initial: boolean }): string {
  try {
    return appHref(linkPath(path));
  } catch {
    return path;
  }
}
