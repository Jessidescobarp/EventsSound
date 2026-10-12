import { useCallback, useEffect, useState } from "react";
import { onApiSuccess } from "../api/activity";
import { checkHealth } from "../api/health";
import { getApiBaseUrl } from "../env";

/**
 * checking: first request in flight (silent)
 * waking: the backend is slow or failed; Render free instances sleep after idle
 * ok: /health answered
 * unavailable: the retry window ended
 */
export type BackendStatus = "checking" | "waking" | "ok" | "unavailable";

// Render free instances can take about a minute to wake up.
const RETRY_WINDOW_MS = 90_000;
const RETRY_INTERVAL_MS = 5_000;
const REQUEST_TIMEOUT_MS = 10_000;
const SLOW_AFTER_MS = 3_000;

/** Polls GET /health with a bounded window and exposes retry() for a fresh window. */
export function useBackendStatus() {
  const [status, setStatus] = useState<BackendStatus>("checking");
  const [run, setRun] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let paused = false; // a retry was due while the tab was hidden
    const deadline = Date.now() + RETRY_WINDOW_MS;
    const slowTimer = setTimeout(() => {
      setStatus((current) => (current === "checking" ? "waking" : current));
    }, SLOW_AFTER_MS);

    // Any valid API response proves the server is up: stop probing and clear the banner.
    const offSuccess = onApiSuccess(() => {
      cancelled = true;
      controller?.abort();
      clearTimeout(timer);
      clearTimeout(slowTimer);
      setStatus("ok");
    });

    // Do not poll from a background tab; pick up again when it becomes visible.
    const onVisibility = () => {
      if (document.hidden || !paused) return;
      paused = false;
      if (Date.now() + RETRY_INTERVAL_MS >= deadline) {
        setStatus("checking"); // the window elapsed while hidden: start a fresh one
        setRun((value) => value + 1);
      } else {
        void attempt();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    const attempt = async () => {
      try {
        getApiBaseUrl();
      } catch (error) {
        console.error(error);
        setStatus("unavailable");
        return;
      }
      // Each attempt is bounded so a hung cold-start request cannot outlive the window.
      controller = new AbortController();
      const current = controller;
      const abortTimer = setTimeout(
        () => current.abort(),
        Math.min(REQUEST_TIMEOUT_MS, deadline - Date.now()),
      );
      try {
        await checkHealth(current.signal);
        if (!cancelled) setStatus("ok");
      } catch {
        if (cancelled) return;
        if (Date.now() + RETRY_INTERVAL_MS >= deadline) {
          setStatus("unavailable");
        } else {
          setStatus("waking");
          timer = setTimeout(() => {
            if (document.hidden) paused = true;
            else void attempt();
          }, RETRY_INTERVAL_MS);
        }
      } finally {
        clearTimeout(abortTimer);
      }
    };

    void attempt();
    return () => {
      cancelled = true;
      controller?.abort();
      clearTimeout(timer);
      clearTimeout(slowTimer);
      offSuccess();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [run]);

  const retry = useCallback(() => {
    setStatus("checking");
    setRun((value) => value + 1);
  }, []);

  return { status, retry };
}
