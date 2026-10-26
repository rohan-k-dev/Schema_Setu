"use client";

/**
 * AuthContext — global authentication state for the SchemeSetu frontend.
 *
 * Session strategy (server-managed):
 *  - The session token is an HttpOnly cookie set by the backend. JavaScript can
 *    never read it, so a script injected into the page cannot steal it.
 *  - Nothing is stored in localStorage. On load, GET /auth/session tells us
 *    whether the cookie is still valid and returns the user + CSRF token.
 *  - The CSRF token is kept in memory (lib/api.ts) and sent in the
 *    X-CSRF-Token header on state-changing requests.
 *  - Sessions expire on the server (idle and absolute limits) and are revoked on
 *    logout or password change; a periodic check signs the UI out when that happens.
 */

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
  apiChangePassword,
  apiGetSession,
  apiLogin,
  apiLogout,
  apiLogoutAll,
  apiRegister,
  setCsrfToken,
} from "@/lib/api";
import type { AuthUser, LoginPayload, RegisterPayload, SessionResponse } from "@/lib/types";

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  /** Creates an unverified account; resolves with the server's "check your e-mail" message. */
  register: (payload: RegisterPayload) => Promise<string>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  /** Re-checks the session with the server; returns false when signed out. */
  refreshSession: () => Promise<boolean>;
  /** Call when an API request returned 401: clears the local signed-in state. */
  handleUnauthorized: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const SESSION_CHECK_MS = 5 * 60 * 1000;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const applySession = useCallback((s: SessionResponse | null) => {
    setCsrfToken(s?.csrf_token ?? null);
    setUser(s?.user ?? null);
  }, []);

  const refreshSession = useCallback(async (): Promise<boolean> => {
    try {
      const s = await apiGetSession();
      applySession(s);
      return s !== null;
    } catch {
      return false;          // network error: keep the current state, try again later
    }
  }, [applySession]);

  // Restore the session from the cookie on load, then re-check periodically.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await refreshSession();
      if (!cancelled) setIsLoading(false);
    })();
    const id = setInterval(refreshSession, SESSION_CHECK_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [refreshSession]);

  const login = useCallback(async (payload: LoginPayload) => {
    applySession(await apiLogin(payload));
  }, [applySession]);

  const register = useCallback(async (payload: RegisterPayload) => apiRegister(payload), []);

  const logout = useCallback(async () => {
    try { await apiLogout(); } catch { /* the cookie may already be gone */ }
    applySession(null);
  }, [applySession]);

  const logoutAll = useCallback(async () => {
    try { await apiLogoutAll(); } finally { applySession(null); }
  }, [applySession]);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    applySession(await apiChangePassword(currentPassword, newPassword));
  }, [applySession]);

  const handleUnauthorized = useCallback(() => applySession(null), [applySession]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
        logoutAll,
        changePassword,
        refreshSession,
        handleUnauthorized,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
