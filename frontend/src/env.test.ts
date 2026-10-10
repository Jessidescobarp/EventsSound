import { describe, expect, it, vi } from "vitest";
import { getApiBaseUrl } from "./env";

describe("getApiBaseUrl", () => {
  it("returns VITE_API_BASE_URL without a trailing slash", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example/");
    expect(getApiBaseUrl()).toBe("https://api.example");
  });

  it("fails clearly naming the variable when it is missing", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(() => getApiBaseUrl()).toThrow(/VITE_API_BASE_URL/);
  });
});
