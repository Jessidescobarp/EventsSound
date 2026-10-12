import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, MAX_RESPONSE_CHARS } from "./client";

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    }),
  );

const hungFetch = (_input: RequestInfo | URL, init?: RequestInit) =>
  new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("Aborted", "AbortError")),
    );
  });

const asString = (value: unknown): string => {
  if (typeof value !== "string") throw new Error("not a string");
  return value;
};

const codeOf = async (promise: Promise<unknown>) => {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error.code;
    throw error;
  }
  return "resolved";
};

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example/");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("requests base URL + path with an Accept header and returns the parsed value", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => json("hola"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/greeting", { parse: asString })).resolves.toBe("hola");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/greeting");
    const init = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("Accept")).toBe("application/json");
    expect(init?.credentials).toBe("omit");
  });

  it.each([
    [404, "not_found"],
    [500, "server"],
    [503, "server"],
    [400, "http"],
    [429, "http"],
  ])("maps HTTP %i to %s", async (status, code) => {
    vi.stubGlobal("fetch", vi.fn(() => json({ detail: "x" }, status)));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe(code);
  });

  it("exposes the HTTP status on the error", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json({}, 503)));
    const error = await apiFetch("/x", { parse: asString }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
  });

  it("maps a rejected fetch to network", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("down"))));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("network");
  });

  it("maps a missing or malformed base URL to config without calling fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("VITE_API_BASE_URL", "");
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("config");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a path that does not start with a slash", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(codeOf(apiFetch("x", { parse: asString }))).resolves.toBe("config");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("times out a hung request with the timeout code", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(hungFetch));
    const result = codeOf(apiFetch("/x", { parse: asString, timeoutMs: 5_000 }));
    await vi.advanceTimersByTimeAsync(4_999);
    let settled = false;
    void result.then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    await expect(result).resolves.toBe("timeout");
  });

  it("reports aborted when the caller aborts", async () => {
    vi.stubGlobal("fetch", vi.fn(hungFetch));
    const controller = new AbortController();
    const result = codeOf(
      apiFetch("/x", { parse: asString, signal: controller.signal }),
    );
    controller.abort();
    await expect(result).resolves.toBe("aborted");
  });

  it("reports aborted without calling fetch when the signal is already aborted", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await codeOf(
      apiFetch("/x", { parse: asString, signal: AbortSignal.abort() }),
    );
    expect(result).toBe("aborted");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps a body that is not JSON to invalid_response", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("<html>oops</html>"))));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("invalid_response");
  });

  it("maps a parse guard failure to invalid_response", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json(42)));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("invalid_response");
  });

  it("refuses a huge declared Content-Length without reading the body", async () => {
    const response = new Response("{}", {
      headers: { "Content-Length": String(MAX_RESPONSE_CHARS + 1) },
    });
    const textSpy = vi.spyOn(response, "text");
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
    expect(textSpy).not.toHaveBeenCalled();
  });

  it("refuses a huge body even when Content-Length is absent", async () => {
    const big = JSON.stringify("a".repeat(MAX_RESPONSE_CHARS));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(big))));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
  });
});
