"use client";

/**
 * AuthContext — global authentication state for the SchemeSetu frontend.
 *
 * Provides:
 *  - Current auth user (farmer_id, email, full_name)
 *  - Access token (kept in memory; never in localStorage for XSS safety)
 *  - Refresh token (stored in localStorage with a short-expiry flag)
 *  - login(), register(), logout(), refreshSession() helpers
 *
 * Token strategy:
 *  - Access token → React state (in-memory, lost on refresh → use refreshSession)
 *  - Refresh token → localStorage (persisted, but rotate on every use)
 *
 * Session expiry:
 *  - An interval calls refreshSession() 2 minutes before access token expires.
 *  - If refresh fails, the user is signed out automatically.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  apiLogin,
  apiLogout,
  apiRefreshToken,
  apiRegister,
} from "@/lib/api";
import type { AuthUser, LoginPayload, RegisterPayload } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<boolean>;
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_TOKEN_KEY = "schemesetu_refresh_token";
const FARMER_ID_KEY = "schemesetu_farmer_id";

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Track the interval for auto-refresh
  const refreshIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const clearSession = useCallback(() => {
    setUser(null);
    setAccessToken(null);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(FARMER_ID_KEY);
    if (refreshIntervalRef.current) {
      clearInterval(refreshIntervalRef.current);
      refreshIntervalRef.current = null;
    }
  }, []);

  const persistSession = useCallback(
    (tokens: { access_token: string; refresh_token: string; farmer_id: string; expires_in: number },
     userInfo: AuthUser) => {
      setAccessToken(tokens.access_token);
      setUser(userInfo);
      localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
      localStorage.setItem(FARMER_ID_KEY, tokens.farmer_id);

      // Schedule a silent refresh 2 minutes before the access token expires
      if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current);
      const refreshMs = Math.max((tokens.expires_in - 120) * 1000, 30_000);
      refreshIntervalRef.current = setInterval(async () => {
        const ok = await refreshSession();
        if (!ok) clearSession();
      }, refreshMs);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // ── refreshSession ───────────────────────────────────────────────────────────

  const refreshSession = useCallback(async (): Promise<boolean> => {
    const storedRefresh = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!storedRefresh) return false;
    try {
      const tokens = await apiRefreshToken(storedRefresh);
      const userInfo: AuthUser = { farmer_id: tokens.farmer_id, email: "" };
      persistSession(tokens, userInfo);
      return true;
    } catch {
      clearSession();
      return false;
    }
  }, [clearSession, persistSession]);

  // ── Boot: restore session from stored refresh token ─────────────────────────

  useEffect(() => {
    (async () => {
      const storedRefresh = localStorage.getItem(REFRESH_TOKEN_KEY);
      if (storedRefresh) {
        await refreshSession();
      }
      setIsLoading(false);
    })();
    return () => {
      if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current);
    };
  }, [refreshSession]);

  // ── login ────────────────────────────────────────────────────────────────────

  const login = useCallback(
    async (payload: LoginPayload) => {
      const tokens = await apiLogin(payload);
      const userInfo: AuthUser = {
        farmer_id: tokens.farmer_id,
        email: payload.email,
      };
      persistSession(tokens, userInfo);
    },
    [persistSession]
  );

  // ── register ─────────────────────────────────────────────────────────────────

  const register = useCallback(
    async (payload: RegisterPayload) => {
      const tokens = await apiRegister(payload);
      const userInfo: AuthUser = {
        farmer_id: tokens.farmer_id,
        email: payload.email,
        full_name: payload.full_name,
      };
      persistSession(tokens, userInfo);
    },
    [persistSession]
  );

  // ── logout ───────────────────────────────────────────────────────────────────

  const logout = useCallback(async () => {
    const storedRefresh = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (storedRefresh) {
      try { await apiLogout(storedRefresh); } catch { /* best-effort */ }
    }
    clearSession();
  }, [clearSession]);

  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <AuthContext.Provider
      value={{
        user,
        accessToken,
        isLoading,
        isAuthenticated: !!user && !!accessToken,
        login,
        register,
        logout,
        refreshSession,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
