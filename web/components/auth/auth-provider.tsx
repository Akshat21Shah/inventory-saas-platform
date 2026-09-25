"use client";

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
  can: (permission: string) => boolean;
  signIn: (access: string, expiresAt: string | undefined) => Promise<Me | null>;
  signOut: () => Promise<void>;
  reloadMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [blockedCode, setBlockedCode] = useState<string | null>(null);

  const loadMe = useCallback(async (): Promise<Me | null> => {
    try {
      const response = await authMeRetrieve();
      setMe(response.data);
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
  }, []);

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
    setMe(null);
    setStatus("anonymous");
  }, [me]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      me,
      blockedCode,
      can: (permission) => Boolean(me?.permissions.includes(permission)),
      signIn,
      signOut,
      reloadMe: async () => {
        await loadMe();
      },
    }),
    [status, me, blockedCode, signIn, signOut, loadMe],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
