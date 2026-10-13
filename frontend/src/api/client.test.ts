import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, MAX_RESPONSE_BYTES } from "./client";

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
      headers: { "Content-Length": String(MAX_RESPONSE_BYTES + 1) },
    });
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
    expect(response.bodyUsed).toBe(false);
  });

  it("refuses a huge body even when Content-Length is absent", async () => {
    const big = JSON.stringify("a".repeat(MAX_RESPONSE_BYTES));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(big))));
    await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
  });

  describe("body size cap while streaming", () => {
    const streamOf = (chunks: number, chunkBytes: number, headers: HeadersInit = {}) => {
      let pulled = 0;
      let cancelled = false;
      const body = new ReadableStream<Uint8Array>({
        pull(controller) {
          pulled += 1;
          if (pulled > chunks) {
            controller.close();
            return;
          }
          controller.enqueue(new Uint8Array(chunkBytes).fill(97));
        },
        cancel() {
          cancelled = true;
        },
      });
      return {
        response: new Response(body, { headers }),
        stats: () => ({ pulled, cancelled }),
      };
    };

    it("stops reading and cancels the stream once the cap is exceeded", async () => {
      const { response, stats } = streamOf(100, 100_000);
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
      await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
      expect(stats().cancelled).toBe(true);
      expect(stats().pulled).toBeLessThan(20);
    });

    it("caps by bytes, not characters (multi-byte text)", async () => {
      const text = JSON.stringify("é".repeat(MAX_RESPONSE_BYTES / 2 + 10));
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(text))));
      await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
    });

    it("ignores a lying small Content-Length and still caps the stream", async () => {
      const { response } = streamOf(50, 100_000, { "Content-Length": "10" });
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
      await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
    });

    it("accepts a cross-origin response whose Content-Length is not exposed", async () => {
      vi.stubGlobal("fetch", vi.fn(() => json("ok"))); // no Content-Length header at all
      await expect(apiFetch("/x", { parse: asString })).resolves.toBe("ok");
    });

    it("ignores a non-numeric Content-Length", async () => {
      vi.stubGlobal("fetch", vi.fn(() => json("ok", 200, { "Content-Length": "abc" })));
      await expect(apiFetch("/x", { parse: asString })).resolves.toBe("ok");
    });

    it("accepts a body of exactly the cap and refuses one byte more", async () => {
      const exact = (n: number) => {
        const overhead = JSON.stringify("").length;
        return JSON.stringify("a".repeat(n - overhead));
      };
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(exact(MAX_RESPONSE_BYTES)))));
      await expect(apiFetch("/x", { parse: asString })).resolves.toHaveLength(MAX_RESPONSE_BYTES - 2);
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(exact(MAX_RESPONSE_BYTES + 1)))));
      await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
    });

    it("falls back to text() with the same cap when the response has no body stream", async () => {
      const fake = (text: string) =>
        ({
          ok: true,
          status: 200,
          headers: new Headers(),
          body: null,
          text: async () => text,
        }) as unknown as Response;
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(fake(JSON.stringify("hola")))));
      await expect(apiFetch("/x", { parse: asString })).resolves.toBe("hola");
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(fake("a".repeat(MAX_RESPONSE_BYTES + 1)))));
      await expect(codeOf(apiFetch("/x", { parse: asString }))).resolves.toBe("too_large");
    });

    it("maps an abort while streaming to aborted", async () => {
      const controller = new AbortController();
      const body = new ReadableStream<Uint8Array>({
        pull() {
          return new Promise(() => {});
        },
      });
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(body))));
      const result = codeOf(apiFetch("/x", { parse: asString, signal: controller.signal }));
      await Promise.resolve();
      controller.abort();
      await expect(result).resolves.toBe("aborted");
    });
  });
});

describe("apiFetch POST and error bodies", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  });

  it("sends the JSON body with a content type", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => json("ok"));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/echo", { parse: asString, method: "POST", jsonBody: { a: 1 } });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe('{"a":1}');
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  const failure = async (body: unknown, headers: HeadersInit = {}) => {
    vi.stubGlobal("fetch", vi.fn(() => json(body, 429, headers)));
    const error = await apiFetch("/x", { parse: asString }).catch((e: unknown) => e);
    if (!(error instanceof ApiError)) throw new Error("expected ApiError");
    return error;
  };

  it.each([
    [{ detail: "rate_limited", message: "Espera." }, { "Retry-After": "37" }, "rate_limited", "Espera.", 37],
    [{ detail: "rate_limited", message: "x".repeat(200) }, { "Retry-After": "300" }, "rate_limited", "x".repeat(200), 300],
    [{ detail: "rate_limited", message: "x".repeat(201) }, { "Retry-After": "99999" }, "rate_limited", undefined, 300],
    [{ detail: "Bad<Code>", message: "a\nb" }, { "Retry-After": "soon" }, undefined, undefined, undefined],
    [{ detail: 5, message: { html: "<b>" } }, { "Retry-After": "0" }, undefined, undefined, undefined],
  ])("keeps only validated error fields: %#", async (body, headers, detail, message, retry) => {
    const error = await failure(body, headers);
    expect([error.detail, error.serverMessage, error.retryAfterSeconds]).toEqual([detail, message, retry]);
  });
});
