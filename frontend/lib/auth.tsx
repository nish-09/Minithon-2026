"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import type { Me } from "./types";

interface AuthCtx {
  user: Me | null;
  loading: boolean;
  /** set when the session could not be verified because the API was unreachable (token is kept) */
  connectionError: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (body: { name: string; email: string; password: string; phone?: string }) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (u: Me) => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const clear = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      return;
    }
    try {
      setUser(await api<Me>("/api/auth/me"));
      setConnectionError(null);
    } catch (e) {
      // 401 already cleared the token via the unauthorized handler. Anything else (offline, 5xx) must not log the user out.
      if (getToken()) setConnectionError(e instanceof Error ? e.message : "Can't reach NEXA.");
      throw e;
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(clear);
    (async () => {
      try {
        await refresh();
      } catch {
        // network failure keeps the token (we may just be offline); a 401 already cleared it
      } finally {
        setLoading(false);
      }
    })();
    return () => setUnauthorizedHandler(null);
  }, [clear, refresh]);

  const value = useMemo<AuthCtx>(
    () => ({
      user,
      loading,
      connectionError,
      setUser,
      refresh,
      login: async (email, password) => {
        const r = await api<{ token: string; user: Me }>("/api/auth/login", { method: "POST", body: { email, password }, token: null });
        setToken(r.token);
        setUser(r.user);
      },
      register: async (body) => {
        const r = await api<{ token: string; user: Me }>("/api/auth/register", { method: "POST", body, token: null });
        setToken(r.token);
        setUser(r.user);
      },
      logout: async () => {
        try {
          await api("/api/auth/logout", { method: "POST" });
        } catch {
          /* token is dropped locally regardless */
        }
        clear();
      },
    }),
    [user, loading, connectionError, refresh, clear],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside AuthProvider");
  return c;
}
