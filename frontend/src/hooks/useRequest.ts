import { useCallback, useEffect, useState } from "react";
import { ApiError, type ApiErrorCode } from "../api/client";

export type RequestState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };

export interface UseRequestOptions {
  /** Extra attempts after the first one, only for transient errors. */
  retries?: number;
  /** Delay before retry n (the last value repeats). */
  retryDelaysMs?: readonly number[];
}

const DEFAULT_RETRIES = 2;
const DEFAULT_DELAYS_MS: readonly number[] = [1_000, 3_000];
// A 404, a bad payload or a configuration error will not fix itself by retrying.
const TRANSIENT: ReadonlySet<ApiErrorCode> = new Set(["network", "timeout", "server"]);

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError("network", "Unexpected error.");
}

/**
 * Runs an async GET once on mount (and on reload()), with a bounded retry for
 * transient errors. `fn` must be referentially stable (module-level or useCallback).
 * Unmounting aborts the in-flight request and cancels pending retries.
 */
export function useRequest<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  { retries = DEFAULT_RETRIES, retryDelaysMs = DEFAULT_DELAYS_MS }: UseRequestOptions = {},
) {
  const [state, setState] = useState<RequestState<T>>({ status: "loading" });
  const [run, setRun] = useState(0);
  // Primitive dependency: callers may pass a fresh array literal on every render.
  const delaysKey = retryDelaysMs.join(",");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const delays = delaysKey.split(",").map(Number);

    const attempt = async (n: number) => {
      try {
        const data = await fn(controller.signal);
        if (!cancelled) setState({ status: "success", data });
      } catch (caught) {
        if (cancelled) return;
        const error = toApiError(caught);
        if (error.code === "aborted") return;
        if (TRANSIENT.has(error.code) && n < retries) {
          const delay = delays[Math.min(n, delays.length - 1)] ?? 1_000;
          timer = setTimeout(() => void attempt(n + 1), delay);
        } else {
          setState({ status: "error", error });
        }
      }
    };

    void attempt(0);
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [fn, retries, delaysKey, run]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setRun((value) => value + 1);
  }, []);

  return { state, reload };
}
