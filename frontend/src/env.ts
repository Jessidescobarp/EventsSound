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
