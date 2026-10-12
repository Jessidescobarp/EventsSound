/**
 * The ONE predicate for demo mode: true only when VITE_USE_MOCKS is exactly "true".
 * Vite resolves it at dev/build time from the process environment (dev.ps1 -Mocks,
 * tests). Vite would also read it from .env files in envDir (the repo root), but this
 * project never puts it there; vite.config.ts refuses a production build with it on.
 */
export function isMockMode(): boolean {
  return import.meta.env.VITE_USE_MOCKS === "true";
}

/** Returns the backend base URL from VITE_API_BASE_URL, without a trailing slash. */
export function getApiBaseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (!value) {
    throw new Error(
      "VITE_API_BASE_URL is not set. Define it in frontend/.env.local (see .env.example).",
    );
  }
  if (!/^https?:\/\//.test(value)) {
    throw new Error("VITE_API_BASE_URL must start with http:// or https://.");
  }
  return value.replace(/\/+$/, "");
}
