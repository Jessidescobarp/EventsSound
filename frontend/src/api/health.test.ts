import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, MAX_RESPONSE_BYTES } from "./client";
import { checkHealth } from "./health";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("checkHealth", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  });

  it("goes through apiFetch: GET /health, credentials omitted, Accept header", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => reply({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(checkHealth()).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/health");
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("omit");
    expect(new Headers(init?.headers).get("Accept")).toBe("application/json");
  });

  it.each([
    ["wrong status value", () => reply({ status: "down" }), "invalid_response"],
    ["not an object", () => reply("ok"), "invalid_response"],
    ["503", () => reply({ status: "ok" }, 503), "server"],
    ["404", () => reply({}, 404), "not_found"],
    ["network error", () => Promise.reject(new TypeError("x")), "network"],
    [
      "oversized body",
      () => Promise.resolve(new Response("a".repeat(MAX_RESPONSE_BYTES + 1))),
      "too_large",
    ],
  ])("rejects with an ApiError for %s", async (_n, impl, code) => {
    vi.stubGlobal("fetch", vi.fn(impl));
    const error = await checkHealth().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe(code);
  });
});
