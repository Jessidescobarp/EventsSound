import { getApiBaseUrl } from "../env";

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

/** Upper bound for a response body (UTF-16 code units). The catalog is about 10 KB. */
export const MAX_RESPONSE_CHARS = 1_000_000;
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

    const declared = Number(response.headers.get("Content-Length"));
    if (Number.isFinite(declared) && declared > MAX_RESPONSE_CHARS) {
      throw new ApiError("too_large", "Response too large.");
    }

    let text: string;
    try {
      text = await response.text();
    } catch {
      throw classifyAbort(timedOut, signal) ?? new ApiError("network", "Network error.");
    }
    if (text.length > MAX_RESPONSE_CHARS) throw new ApiError("too_large", "Response too large.");

    try {
      return parse(JSON.parse(text));
    } catch {
      throw new ApiError("invalid_response", "Response does not match the expected shape.");
    }
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCallerAbort);
  }
}

function classifyAbort(timedOut: boolean, signal?: AbortSignal): ApiError | undefined {
  if (timedOut) return new ApiError("timeout", "Request timed out.");
  if (signal?.aborted) return new ApiError("aborted", "Request aborted.");
  return undefined;
}
