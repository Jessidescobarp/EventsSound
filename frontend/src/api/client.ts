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
  /** Machine code from a validated backend error body (`{"detail": "rate_limited"}`). */
  readonly detail?: string;
  /** Short customer sentence from a validated backend error body; render as text only. */
  readonly serverMessage?: string;
  /** Bounded `Retry-After` seconds (1 to MAX_RETRY_AFTER_SECONDS) when the header is usable. */
  readonly retryAfterSeconds?: number;

  constructor(code: ApiErrorCode, message: string, status?: number, extra: ErrorExtra = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = extra.detail;
    this.serverMessage = extra.serverMessage;
    this.retryAfterSeconds = extra.retryAfterSeconds;
  }
}

interface ErrorExtra {
  detail?: string;
  serverMessage?: string;
  retryAfterSeconds?: number;
}

// C0/C1 controls (incl. newline, tab, NUL, DEL) and bidirectional overrides/isolates.
// eslint-disable-next-line no-control-regex
const FORBIDDEN_CHARS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/;

/** True when untrusted text carries control or bidirectional characters. */
export function hasForbiddenChars(value: string): boolean {
  return FORBIDDEN_CHARS.test(value);
}

const FORBIDDEN_CHARS_GLOBAL = new RegExp(FORBIDDEN_CHARS.source, "g");

/** Replaces control and bidirectional characters with a space (for free text that is shown, not parsed). */
export function replaceForbiddenChars(value: string): string {
  return value.replace(FORBIDDEN_CHARS_GLOBAL, " ");
}

/** Upper bound for a response body in bytes. The catalog is about 10 KB. */
export const MAX_RESPONSE_BYTES = 1_000_000;
export const DEFAULT_TIMEOUT_MS = 10_000;
export const MAX_RETRY_AFTER_SECONDS = 300;
const MAX_ERROR_MESSAGE_CHARS = 200;

export interface ApiFetchOptions<T> {
  /** Typed guard: receives untrusted JSON and must return T or throw. */
  parse: (json: unknown) => T;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Defaults to GET. A POST or PUT sends `jsonBody` serialized as JSON. */
  method?: "GET" | "POST" | "PUT";
  jsonBody?: unknown;
  /** Bearer token for protected routes. Never logged; cookies stay off either way. */
  token?: string;
}

/**
 * GET (or POST) JSON from the backend with a timeout, cancellation, a size cap and a runtime
 * guard. Every failure is an ApiError with a stable code; nothing else is thrown.
 * No cookies are sent: protected routes take a bearer token (`token`).
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions<T>): Promise<T> {
  const { parse, signal, timeoutMs = DEFAULT_TIMEOUT_MS, method = "GET", jsonBody, token } = options;

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
        method,
        headers: {
          Accept: "application/json",
          ...(method !== "GET" ? { "Content-Type": "application/json" } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: method !== "GET" ? JSON.stringify(jsonBody) : undefined,
        credentials: "omit",
        signal: controller.signal,
      });
    } catch {
      throw classifyAbort(timedOut, signal) ?? new ApiError("network", "Network error.");
    }

    if (!response.ok) {
      const { status } = response;
      if (status === 404) throw new ApiError("not_found", "Not found.", status);
      const extra = await readErrorInfo(response, controller.signal);
      if (status >= 500) throw new ApiError("server", `Server error ${status}.`, status, extra);
      throw new ApiError("http", `Unexpected status ${status}.`, status, extra);
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

/**
 * Best-effort read of an error body: only a short lowercase `detail` code and a short,
 * control-free `message` survive, plus a bounded Retry-After. Anything else is dropped.
 */
async function readErrorInfo(response: Response, signal: AbortSignal): Promise<ErrorExtra> {
  const info: ErrorExtra = {};
  const retry = Number(response.headers.get("Retry-After"));
  if (Number.isInteger(retry) && retry >= 1) {
    info.retryAfterSeconds = Math.min(retry, MAX_RETRY_AFTER_SECONDS);
  }
  try {
    const body: unknown = JSON.parse(await readCapped(response, signal));
    if (typeof body === "object" && body !== null) {
      const { detail, message } = body as Record<string, unknown>;
      if (typeof detail === "string" && /^[a-z_]{1,48}$/.test(detail)) info.detail = detail;
      if (
        typeof message === "string" &&
        message.trim().length > 0 &&
        message.length <= MAX_ERROR_MESSAGE_CHARS &&
        !hasForbiddenChars(message)
      ) {
        info.serverMessage = message;
      }
    }
  } catch {
    // not JSON, too large or aborted: the status alone classifies the error
  }
  return info;
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
