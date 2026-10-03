/**
 * Who is signed in, to which distributor, with its branding (ADR-061 items 4 and 5). The session
 * itself is in `session.ts`; this keeps the screens' view of it: loading → signed out or in.
 */
import { onlineManager, useQueryClient } from "@tanstack/react-query";
import * as SecureStore from "expo-secure-store";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { authMeRetrieve } from "@/lib/api/generated/endpoints/auth/auth";
import { publicTenantBranding } from "@/lib/api/generated/endpoints/public/public";
import type { Me, PublicBranding } from "@/lib/api/generated/model";
import { sessionEnded } from "@/lib/events";
import { setLanguage } from "@/lib/i18n/language";
import { persister } from "@/lib/offline/persist";
import { forgetThisPhone } from "@/lib/push/push";
import { clearFileStore, fileStore } from "@/lib/storage/file-store";
import { isLocale } from "@/lib/shared/i18n-config";

import {
  endSession,
  restoreSession,
  sessionTenant,
  setSessionTenant,
  startSession,
  type Tokens,
} from "./session";

const BRANDING_KEY = "session.branding";
const ME_KEY = "me"; // the profile, in the app's own files (file-store.ts)

type Status = "loading" | "signedOut" | "signedIn";

interface Auth {
  status: Status;
  me: Me | null;
  branding: PublicBranding | null;
  signIn: (tokens: Tokens) => Promise<void>;
  signOut: () => Promise<void>;
  reload: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

async function cachedBranding(): Promise<PublicBranding | null> {
  const raw = await SecureStore.getItemAsync(BRANDING_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PublicBranding;
  } catch {
    return null;
  }
}

async function loadBranding(slug: string): Promise<PublicBranding | null> {
  try {
    const branding = (await publicTenantBranding(slug)).data;
    await SecureStore.setItemAsync(BRANDING_KEY, JSON.stringify(branding));
    return branding;
  } catch {
    return cachedBranding(); // offline: as last seen
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [branding, setBranding] = useState<PublicBranding | null>(null);

  const loadMe = useCallback(async () => {
    const found = (await authMeRetrieve()).data;
    setMe(found);
    await fileStore.setItem(ME_KEY, JSON.stringify(found)); // for a start without a connection
    if (isLocale(found.language)) await setLanguage(found.language);
    return found;
  }, []);

  const signOut = useCallback(async () => {
    await forgetThisPhone(); // this phone stops getting the shop's messages
    await endSession();
    await persister.removeClient(); // what was saved for offline use
    await clearFileStore();
    await SecureStore.deleteItemAsync(BRANDING_KEY);
    queryClient.clear();
    setMe(null);
    setBranding(null);
    setStatus("signedOut");
  }, [queryClient]);

  const signIn = useCallback(
    async (tokens: Tokens) => {
      await startSession(tokens);
      const found = await loadMe();
      const slug = found.tenant?.slug ?? "";
      await setSessionTenant(slug);
      setBranding(await loadBranding(slug));
      setStatus("signedIn");
    },
    [loadMe],
  );

  const reload = useCallback(async () => {
    await loadMe();
  }, [loadMe]);

  useEffect(() => {
    let alive = true;
    (async () => {
      const slug = await sessionTenant();
      if (!slug || !(await restoreSession())) {
        if (alive) setStatus("signedOut");
        return;
      }
      setBranding(await cachedBranding());
      try {
        await loadMe();
      } catch {
        // Offline start: carry on with the saved session and profile; screens show what was saved.
        const saved = await fileStore.getItem(ME_KEY);
        if (saved && alive) setMe(JSON.parse(saved) as Me);
      }
      const fresh = await loadBranding(slug);
      if (alive) {
        setBranding(fresh);
        setStatus("signedIn");
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadMe]);

  useEffect(() => sessionEnded.listen(() => void signOut()), [signOut]);

  // Back online after a start without a connection: the profile from the server again.
  useEffect(
    () =>
      onlineManager.subscribe((online) => {
        if (online && status === "signedIn") void loadMe().catch(() => undefined);
      }),
    [status, loadMe],
  );

  const value = useMemo(
    () => ({ status, me, branding, signIn, signOut, reload }),
    [status, me, branding, signIn, signOut, reload],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth outside AuthProvider");
  return auth;
}
