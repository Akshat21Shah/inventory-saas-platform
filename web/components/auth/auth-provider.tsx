"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  authImpersonationEnd,
  authLogout,
  authMeRetrieve,
} from "@/lib/api/generated/endpoints/auth/auth";
import type { Me } from "@/lib/api/generated/model";
import { ApiError } from "@/lib/api/errors";
import { SESSION_ENDED_EVENT } from "@/lib/api/fetcher";
import { rememberLanguage } from "@/lib/i18n/client";
import {
  clearAccessToken,
  getAccessToken,
  refreshSession,
  setAccessToken,
} from "@/lib/auth/session";

export type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: AuthStatus;
  me: Me | null;
  /** Error code of the last failed session check (e.g. TENANT_UNAVAILABLE), for a friendly message. */
  blockedCode: string | null;
  /** True after the person signed out here: the next sign-in starts from home, not the page
   * they were on. */
  signedOut: boolean;
  can: (permission: string) => boolean;
  /** An optional module switched on for this business (e-invoices, payments…); screens of a
   * module that is off stay hidden (the server refuses them regardless). */
  feature: (code: string) => boolean;
  signIn: (access: string, expiresAt: string | undefined) => Promise<Me | null>;
  signOut: () => Promise<void>;
  reloadMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [blockedCode, setBlockedCode] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const router = useRouter();

  const loadMe = useCallback(async (): Promise<Me | null> => {
    try {
      const response = await authMeRetrieve();
      setMe(response.data);
      // Show the person's language (ADR-060): the server says which one they see.
      if (rememberLanguage(response.data.language)) router.refresh();
      setBlockedCode(null);
      setStatus("authenticated");
      return response.data;
    } catch (error) {
      clearAccessToken();
      setMe(null);
      setBlockedCode(error instanceof ApiError ? error.code : null);
      setStatus("anonymous");
      return null;
    }
  }, [router]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ok = getAccessToken() !== null || (await refreshSession());
      if (cancelled) return;
      if (ok) await loadMe();
      else setStatus("anonymous");
    })();
    const onEnded = () => {
      setMe(null);
      setStatus("anonymous");
    };
    window.addEventListener(SESSION_ENDED_EVENT, onEnded);
    return () => {
      cancelled = true;
      window.removeEventListener(SESSION_ENDED_EVENT, onEnded);
    };
  }, [loadMe]);

  const signIn = useCallback(
    async (access: string, expiresAt: string | undefined) => {
      setAccessToken(access, expiresAt);
      setSignedOut(false);
      return loadMe();
    },
    [loadMe],
  );

  const signOut = useCallback(async () => {
    try {
      if (me?.impersonation) await authImpersonationEnd();
      else await authLogout({});
    } catch {
      // The session is ended locally either way.
    }
    clearAccessToken();
    setSignedOut(true);
    setMe(null);
    setStatus("anonymous");
  }, [me]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      me,
      blockedCode,
      signedOut,
      can: (permission) => Boolean(me?.permissions.includes(permission)),
      feature: (code) => Boolean(me?.features?.[code]),
      signIn,
      signOut,
      reloadMe: async () => {
        await loadMe();
      },
    }),
    [status, me, blockedCode, signedOut, signIn, signOut, loadMe],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
