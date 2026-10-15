import { createContext, useContext } from "react";
import type { LoginResult } from "../api/auth";
import type { Session } from "./session";

export interface AuthState {
  session: Session | null;
  /** Set when the session ended on its own (token expired or rejected), until the next sign in. */
  expired: boolean;
  signIn: (result: LoginResult) => void;
  signOut: () => void;
  /** The server refused the token: drop the session and remember why. */
  expireSession: () => void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (value === null) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
