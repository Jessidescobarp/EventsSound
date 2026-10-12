import { getApiBaseUrl } from "../env";
import { notifyApiSuccess } from "./activity";

export type ApiErrorCode =
  | "config" // base URL missing/invalid or bad path: a programming or deploy error
  | "network" // DNS, offline, CORS, connection refused
  | "timeout" // the request exceeded timeoutMs
  | "aborted" // the caller cancelled
  | "not_found" // HTTP 404 (endpoint not deployed yet)
  | "server" // HTTP 5xx
  | "http" // any other non-2xx status
  | "invalid_response" // body is not JSON or does not satisfy the typed guard
  | "too_large"; // body exceeds MAX_RESPONSE_CHARS

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status?: number;

  constructor(code: ApiErrorCode, message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

/** Upper bound for a response body in bytes. The catalog is about 10 KB. */
export const MAX_RESPONSE_BYTES = 1_000_000;
export const DEFAULT_TIMEOUT_MS = 10_000;

export interface ApiFetchOptions<T> {
  /** Typed guard: receives untrusted JSON and must return T or throw. */
  parse: (json: unknown) => T;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/**
 * GET JSON from the backend with a timeout, cancellation, a size cap and a runtime
 * guard. Every failure is an ApiError with a stable code; nothing else is thrown.
 * No cookies are sent (the API uses bearer tokens, added later).
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions<T>): Promise<T> {
  const { parse, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;

  if (!path.startsWith("/")) throw new ApiError("config", "API path must start with '/'.");
  let base: string;
  try {
    base = getApiBaseUrl();
  } catch (error) {
    throw new ApiError("config", error instanceof Error ? error.message : "Invalid API URL.");
  }
  if (signal?.aborted) throw new ApiError("aborted", "Request aborted.");

  const controller = new AbortController();
  let timedOut = false;
  const onCallerAbort = () => controller.abort();
  signal?.addEventListener("abort", onCallerAbort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    let response: Response;
    try {
      response = await fetch(`${base}${path}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "omit",
        signal: controller.signal,
      });
    } catch {
      throw classifyAbort(timedOut, signal) ?? new ApiError("network", "Network error.");
    }

    if (!response.ok) {
      const { status } = response;
      if (status === 404) throw new ApiError("not_found", "Not found.", status);
      if (status >= 500) throw new ApiError("server", `Server error ${status}.`, status);
      throw new ApiError("http", `Unexpected status ${status}.`, status);
    }

    // Content-Length is only an early exit: cross-origin responses do not expose it and
    // it can lie, so the real cap is enforced while reading.
    const declared = Number(response.headers.get("Content-Length"));
    if (Number.isFinite(declared) && declared > MAX_RESPONSE_BYTES) {
      throw new ApiError("too_large", "Response too large.");
    }

    let text: string;
    try {
      text = await readCapped(response, controller.signal);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw classifyAbort(timedOut, signal) ?? new ApiError("network", "Network error.");
    }

    let value: T;
    try {
      value = parse(JSON.parse(text));
    } catch {
      throw new ApiError("invalid_response", "Response does not match the expected shape.");
    }
    notifyApiSuccess();
    return value;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCallerAbort);
  }
}

/** Reads the body as UTF-8 text, refusing to buffer more than MAX_RESPONSE_BYTES. */
async function readCapped(response: Response, signal: AbortSignal): Promise<string> {
  const tooLarge = () => new ApiError("too_large", "Response too large.");
  if (!response.body) {
    const text = await response.text(); // no stream available: same cap, after the fact
    if (new Blob([text]).size > MAX_RESPONSE_BYTES) throw tooLarge();
    return text;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  // A stalled stream does not always error on abort, so cancel the reader ourselves.
  const onAbort = () => void reader.cancel().catch(() => undefined);
  signal.addEventListener("abort", onAbort, { once: true });
  let received = 0;
  let text = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (signal.aborted) throw new Error("aborted");
      if (done) break;
      received += value.byteLength;
      if (received > MAX_RESPONSE_BYTES) {
        await reader.cancel().catch(() => undefined);
        throw tooLarge();
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    signal.removeEventListener("abort", onAbort);
  }
}

function classifyAbort(timedOut: boolean, signal?: AbortSignal): ApiError | undefined {
  if (timedOut) return new ApiError("timeout", "Request timed out.");
  if (signal?.aborted) return new ApiError("aborted", "Request aborted.");
  return undefined;
}
