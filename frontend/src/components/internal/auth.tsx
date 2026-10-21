"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api } from "@/lib/api";

/**
 * Internal (ops/admin) session. Without a sign-in the internal screens are a read-only
 * demo view; signing in with the environment-configured credentials enables edits.
 */

const KEY = "lendwise.internal.v1";

export interface InternalUser {
  token: string;
  role: "ops" | "admin";
  username: string;
}

interface Ctx {
  user: InternalUser | null;
  ready: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
  /** Call when the API says the token is no longer valid. */
  expire: () => void;
}

const InternalAuth = createContext<Ctx | null>(null);

export function InternalAuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<InternalUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(KEY);
      if (raw) setUser(JSON.parse(raw));
    } catch {
      /* storage unavailable: stay read-only */
    }
    setReady(true);
  }, []);

  const persist = (u: InternalUser | null) => {
    setUser(u);
    try {
      if (u) sessionStorage.setItem(KEY, JSON.stringify(u));
      else sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  };

  const signIn = useCallback(async (username: string, password: string) => {
    const { data } = await api<{ access_token: string; role: "ops" | "admin" }>("/auth/login", {
      method: "POST",
      body: { username, password },
    });
    persist({ token: data.access_token, role: data.role, username });
  }, []);

  const signOut = useCallback(() => persist(null), []);

  return (
    <InternalAuth.Provider value={{ user, ready, signIn, signOut, expire: signOut }}>{children}</InternalAuth.Provider>
  );
}

export function useInternalAuth(): Ctx {
  const ctx = useContext(InternalAuth);
  if (!ctx) throw new Error("useInternalAuth must be used inside InternalAuthProvider");
  return ctx;
}
