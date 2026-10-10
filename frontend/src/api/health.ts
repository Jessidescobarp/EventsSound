import { getApiBaseUrl } from "../env";

/** Resolves when GET /health answers 200 {"status":"ok"}; rejects otherwise. */
export async function checkHealth(): Promise<void> {
  const response = await fetch(`${getApiBaseUrl()}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }
  const body = (await response.json()) as { status?: string };
  if (body.status !== "ok") {
    throw new Error("Health check returned an unexpected body");
  }
}
