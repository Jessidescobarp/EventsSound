import type { Role } from "../api/auth";

/**
 * The login session lives in sessionStorage (cleared when the tab closes). Storage can be
 * blocked or throw (private windows, disabled site data): every access is guarded and the app
 * keeps working with the in-memory session only.
 */
export interface Session {
  token: string;
  role: Role;
  /** Epoch milliseconds. */
  expiresAt: number;
}

const KEY = "eventsound.session";
const JWT_SHAPE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;

function isSession(value: unknown): value is Session {
  if (typeof value !== "object" || value === null) return false;
  const { token, role, expiresAt } = value as Record<string, unknown>;
  return (
    typeof token === "string" &&
    token.length <= 2000 &&
    JWT_SHAPE.test(token) &&
    (role === "client" || role === "admin") &&
    typeof expiresAt === "number" &&
    Number.isFinite(expiresAt)
  );
}

/** The stored session, or null when there is none, it is damaged or it already expired. */
export function readSession(now: number = Date.now()): Session | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (isSession(parsed) && parsed.expiresAt > now) return parsed;
  } catch {
    // unreadable storage or broken JSON: behave as signed out
  }
  clearSession();
  return null;
}

export function writeSession(session: Session): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // keep the in-memory session only
  }
}

export function clearSession(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // nothing to clear
  }
}
