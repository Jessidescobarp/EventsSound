import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import type { LoginResult } from "../api/auth";
import { AuthContext, type AuthState } from "./authContext";
import { clearSession, readSession, writeSession, type Session } from "./session";

// setTimeout overflows (and fires at once) past 2^31 ms.
const MAX_TIMER_MS = 2 ** 31 - 1;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => readSession());
  const [expired, setExpired] = useState(false);

  const end = useCallback((becauseExpired: boolean) => {
    clearSession();
    setSession(null);
    setExpired(becauseExpired);
  }, []);

  const signIn = useCallback((result: LoginResult) => {
    const next: Session = {
      token: result.token,
      role: result.role,
      expiresAt: Date.now() + result.expiresIn * 1000,
    };
    writeSession(next);
    setSession(next);
    setExpired(false);
  }, []);

  const signOut = useCallback(() => end(false), [end]);
  const expireSession = useCallback(() => end(true), [end]);

  // Leave on the exact expiry instead of waiting for the first 401.
  useEffect(() => {
    if (session === null) return;
    const wait = Math.min(Math.max(session.expiresAt - Date.now(), 0), MAX_TIMER_MS);
    const timer = setTimeout(expireSession, wait);
    return () => clearTimeout(timer);
  }, [session, expireSession]);

  const value = useMemo<AuthState>(
    () => ({ session, expired, signIn, signOut, expireSession }),
    [session, expired, signIn, signOut, expireSession],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
