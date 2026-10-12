import { apiFetch } from "./client";

function parseHealth(json: unknown): true {
  if (typeof json !== "object" || json === null || (json as { status?: unknown }).status !== "ok") {
    throw new Error("unexpected health body");
  }
  return true;
}

/**
 * Resolves when GET /health answers 200 {"status":"ok"}; rejects with an ApiError
 * otherwise. Uses apiFetch, so credentials are omitted and the size cap applies.
 */
export async function checkHealth(signal?: AbortSignal): Promise<void> {
  await apiFetch("/health", { parse: parseHealth, signal });
}
