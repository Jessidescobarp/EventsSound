import { describe, expect, it, vi } from "vitest";
import { getApiBaseUrl, isMockMode } from "./env";

describe("getApiBaseUrl", () => {
  it("returns VITE_API_BASE_URL without a trailing slash", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example/");
    expect(getApiBaseUrl()).toBe("https://api.example");
  });

  it("fails clearly naming the variable when it is missing", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(() => getApiBaseUrl()).toThrow(/VITE_API_BASE_URL/);
  });

  it("fails clearly when the scheme is missing", () => {
    vi.stubEnv("VITE_API_BASE_URL", "api.example");
    expect(() => getApiBaseUrl()).toThrow(/http/);
  });
});

describe("isMockMode", () => {
  it("is on only for the exact string 'true'", () => {
    vi.stubEnv("VITE_USE_MOCKS", "true");
    expect(isMockMode()).toBe(true);
  });

  it.each(["", "false", "1", "TRUE", "yes", " true"])("is off for %j", (value) => {
    vi.stubEnv("VITE_USE_MOCKS", value);
    expect(isMockMode()).toBe(false);
  });
});
