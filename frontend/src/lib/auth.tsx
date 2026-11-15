"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, ApiError } from "./api";
import type { Me, Mode, Theme } from "./types";

interface AuthCtx {
  me: Me | null;
  loading: boolean;
  error: ApiError | null;
  can: (...perms: string[]) => boolean;
  canAny: (...perms: string[]) => boolean;
  refresh: () => Promise<unknown>;
  logout: () => Promise<void>;
  theme: Theme;
  mode: Mode;
  setTheme: (t: Theme) => void;
  setMode: (m: Mode) => void;
  refreshMs: number;
}

const Ctx = createContext<AuthCtx | null>(null);

const LS_THEME = "anm.theme";
const LS_MODE = "anm.mode";

function readLocal<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = window.localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

export function applyTheme(t: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("light", t === "light");
  document.documentElement.classList.toggle("dark", t === "dark");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data, error, isLoading, mutate } = useSWR<Me, ApiError>("/auth/me", (p: string) => api<Me>(p), {
    shouldRetryOnError: false,
    revalidateOnFocus: true,
  });
  const [theme, setThemeState] = useState<Theme>("dark");
  const [mode, setModeState] = useState<Mode>("simple");

  useEffect(() => {
    setThemeState(readLocal<Theme>(LS_THEME, "dark", ["dark", "light"]));
    setModeState(readLocal<Mode>(LS_MODE, "simple", ["simple", "pro"]));
  }, []);

  // Server-side preferences win once the profile loads.
  useEffect(() => {
    const p = data?.preferences;
    if (p?.theme) setThemeState(p.theme);
    if (p?.mode) setModeState(p.mode);
  }, [data?.preferences]);

  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(LS_THEME, theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_MODE, mode);
    } catch {
      /* storage unavailable */
    }
  }, [mode]);

  const savePref = useCallback(
    (body: { theme?: Theme; mode?: Mode }) => {
      if (!data) return;
      api("/auth/preferences", { method: "PATCH", body }).catch(() => undefined);
    },
    [data],
  );

  const value = useMemo<AuthCtx>(() => {
    const perms = new Set(data?.permissions || []);
    return {
      me: data ?? null,
      loading: isLoading,
      error: error ?? null,
      can: (...p) => p.every((x) => perms.has(x)),
      canAny: (...p) => p.some((x) => perms.has(x)),
      refresh: () => mutate(),
      logout: async () => {
        try {
          await api("/auth/logout", { method: "POST" });
        } finally {
          await mutate(undefined, { revalidate: false });
          window.location.href = "/login";
        }
      },
      theme,
      mode,
      setTheme: (t) => {
        setThemeState(t);
        savePref({ theme: t });
      },
      setMode: (m) => {
        setModeState(m);
        savePref({ mode: m });
      },
      refreshMs: Math.max(10, data?.preferences?.refresh_seconds || data?.dashboard_refresh_seconds || 30) * 1000,
    };
  }, [data, error, isLoading, mutate, theme, mode, savePref]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside AuthProvider");
  return c;
}

/** Testing helper: provide a fixed auth context. */
export function MockAuthProvider({ value, children }: { value: Partial<AuthCtx> & { me: Me | null }; children: React.ReactNode }) {
  const perms = new Set(value.me?.permissions || []);
  const full: AuthCtx = {
    loading: false,
    error: null,
    can: (...p) => p.every((x) => perms.has(x)),
    canAny: (...p) => p.some((x) => perms.has(x)),
    refresh: async () => undefined,
    logout: async () => undefined,
    theme: "dark",
    mode: "simple",
    setTheme: () => undefined,
    setMode: () => undefined,
    refreshMs: 30000,
    ...value,
  };
  return <Ctx.Provider value={full}>{children}</Ctx.Provider>;
}
