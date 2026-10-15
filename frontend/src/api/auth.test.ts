import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { classifyLoginError, login, parseLoginResponse } from "./auth";
import { ApiError } from "./client";

const TOKEN = "aaa.bbb.ccc";
const ok = { access_token: TOKEN, token_type: "bearer", expires_in: 3600, role: "admin" };

const reply = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );

describe("login", () => {
  beforeEach(() => vi.stubEnv("VITE_API_BASE_URL", "https://api.example"));
  afterEach(() => vi.unstubAllGlobals());

  it("posts the trimmed email and the password, and returns the session fields", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => reply(ok));
    vi.stubGlobal("fetch", fetchMock);

    const result = await login("  ana@example.com ", "secret-pw");

    expect(result).toEqual({ token: TOKEN, role: "admin", expiresIn: 3600 });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toBe("https://api.example/auth/login");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "ana@example.com", password: "secret-pw" });
  });

  it.each([
    [{ ...ok, access_token: "not-a-jwt" }],
    [{ ...ok, token_type: "basic" }],
    [{ ...ok, role: "owner" }],
    [{ ...ok, expires_in: 5 }],
    [{ ...ok, access_token: undefined }],
    ["nope"],
  ])("rejects a response outside the contract: %#", (body) => {
    expect(() => parseLoginResponse(body)).toThrow();
  });
});

describe("classifyLoginError", () => {
  const api = (code: ApiError["code"], status?: number, detail?: string) =>
    new ApiError(code, "x", status, { detail });

  it.each([
    [api("http", 401, "invalid_credentials"), "invalid_credentials"],
    [api("http", 429, "rate_limited"), "rate_limited"],
    [api("http", 422, "invalid_request"), "invalid"],
    [api("server", 503, "auth_not_configured"), "unavailable"],
    [api("server", 503, "auth_unavailable"), "unavailable"],
    [api("server", 500), "transient"],
    [api("network"), "transient"],
    [api("timeout"), "transient"],
    [api("aborted"), "aborted"],
    [api("http", 401), "unexpected"],
    [new Error("boom"), "unexpected"],
  ])("maps %# to its failure class", (error, expected) => {
    expect(classifyLoginError(error)).toBe(expected);
  });
});
