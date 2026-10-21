import { useEffect, useRef, useState } from "react";
import { classifyConfigError, type ConfigFailure } from "../../api/adminAgentConfig";
import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/authContext";
import { es } from "../../copy/es";

const t = es.agentAdmin;

export interface ConfigError {
  kind: ConfigFailure;
  fields: readonly string[];
  retryAfterSeconds?: number;
}

/** The Spanish sentence for a failure; field names and Retry-After are added when the server sent them. */
export function failureText({ kind, fields, retryAfterSeconds }: ConfigError): string {
  const base = t.errors[kind] ?? t.errors.unexpected ?? "";
  if (kind === "rate_limited" && retryAfterSeconds) return `${base} ${t.retryIn(retryAfterSeconds)}`;
  if (kind === "invalid_config" && fields.length > 0) {
    return `${base} ${t.invalidFields(fields.map((f) => t.fields[f] ?? f).join(", "))}`;
  }
  return base;
}

/** Runs one authenticated config request at a time. A 401 ends the session; unmounting cancels it. */
export function useConfigCall(onFailure?: (error: ConfigError) => void) {
  const { session, expireSession } = useAuth();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ConfigError | null>(null);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);

  useEffect(() => () => controller.current?.abort(), []);

  /** Resolves with the result, or undefined after a failure (stored in `failure`). */
  async function run<T>(call: (token: string, signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    if (inFlight.current) return undefined; // a second submit while one is running is ignored
    inFlight.current = true;
    const mine = new AbortController();
    controller.current = mine;
    setBusy(true);
    setFailure(null);
    try {
      return await call(session?.token ?? "", mine.signal);
    } catch (error) {
      const kind = classifyConfigError(error);
      if (kind === "aborted") return undefined;
      if (kind === "unauthenticated") expireSession();
      const failed: ConfigError = {
        kind,
        fields: error instanceof ApiError ? (error.fields ?? []) : [],
        retryAfterSeconds: error instanceof ApiError ? error.retryAfterSeconds : undefined,
      };
      setFailure(failed);
      onFailure?.(failed);
      return undefined;
    } finally {
      inFlight.current = false;
      if (controller.current === mine) setBusy(false);
    }
  }

  return { busy, failure, run, clearFailure: () => setFailure(null) };
}
