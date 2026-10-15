import { ApiError, apiFetch } from "./client";
import { int, obj, str } from "./parse";

/** Contract of POST /auth/login (backend routes/auth.py). */
export type Role = "client" | "admin";

export interface LoginResult {
  token: string;
  role: Role;
  /** Seconds until the token expires. */
  expiresIn: number;
}

const ROLES: readonly string[] = ["client", "admin"];
const JWT_SHAPE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const MAX_TOKEN_CHARS = 2000;

export function parseLoginResponse(json: unknown): LoginResult {
  const o = obj(json);
  const token = str(o, "access_token", MAX_TOKEN_CHARS);
  const role = str(o, "role", 16);
  if (!JWT_SHAPE.test(token) || o.token_type !== "bearer" || !ROLES.includes(role)) {
    throw new Error("unexpected login response");
  }
  return { token, role: role as Role, expiresIn: int(o, "expires_in", 60, 86_400) };
}

export function login(email: string, password: string, signal?: AbortSignal): Promise<LoginResult> {
  return apiFetch("/auth/login", {
    method: "POST",
    jsonBody: { email: email.trim(), password },
    parse: parseLoginResponse,
    signal,
  });
}

/**
 * invalid_credentials: wrong email or password (one answer for both, by design).
 * rate_limited: too many attempts, wait. unavailable: auth is off or storage is down.
 * invalid: the form was malformed (422). transient: network, timeout or 5xx.
 */
export type LoginFailure =
  | "invalid_credentials"
  | "rate_limited"
  | "unavailable"
  | "invalid"
  | "transient"
  | "unexpected"
  | "aborted";

export function classifyLoginError(error: unknown): LoginFailure {
  if (!(error instanceof ApiError)) return "unexpected";
  const { code, status, detail } = error;
  if (code === "aborted") return "aborted";
  if (status === 401 && detail === "invalid_credentials") return "invalid_credentials";
  if (status === 429) return "rate_limited";
  if (status === 422) return "invalid";
  if (status === 503 && (detail === "auth_not_configured" || detail === "auth_unavailable")) {
    return "unavailable";
  }
  if (code === "network" || code === "timeout" || code === "server") return "transient";
  return "unexpected";
}
