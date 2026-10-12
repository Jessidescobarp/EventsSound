import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBackendStatus } from "./useBackendStatus";

const reply = (body: unknown, status = 200) =>
  Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);

// A fetch that never answers on its own and only settles when aborted.
const hungFetch = (_input: RequestInfo | URL, init?: RequestInit) =>
  new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("Aborted", "AbortError")),
    );
  });

const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe("useBackendStatus", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts as checking while the first request is pending", () => {
    vi.stubGlobal("fetch", vi.fn(hungFetch));
    const { result } = renderHook(() => useBackendStatus());
    expect(result.current.status).toBe("checking");
  });

  it("requests health at the configured base URL and reports ok", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => reply({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus());
    await advance(0);
    expect(result.current.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/health");
  });

  it("switches to waking when the first request is still pending after 3 s", async () => {
    vi.stubGlobal("fetch", vi.fn(hungFetch));
    const { result } = renderHook(() => useBackendStatus());
    await advance(2_900);
    expect(result.current.status).toBe("checking");
    await advance(200);
    expect(result.current.status).toBe("waking");
  });

  it("switches to waking after the first failed attempt and keeps retrying", async () => {
    const fetchMock = vi.fn(() => Promise.reject(new TypeError("cold")));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus());
    await advance(0);
    expect(result.current.status).toBe("waking");
    await advance(30_000);
    expect(result.current.status).toBe("waking");
    expect(fetchMock.mock.calls.length).toBeGreaterThan(2);
  });

  it.each([
    ["rejects", () => Promise.reject(new TypeError("network"))],
    ["returns 503", () => reply({ status: "down" }, 503)],
  ])("reports unavailable after the 90 s window when fetch %s", async (_n, impl) => {
    vi.stubGlobal("fetch", vi.fn(impl));
    const { result } = renderHook(() => useBackendStatus());
    await advance(80_000);
    expect(result.current.status).toBe("waking");
    await advance(10_000);
    expect(result.current.status).toBe("unavailable");
  });

  it("recovers when the backend wakes up within the window", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => Promise.reject(new TypeError("cold")))
      .mockImplementationOnce(() => reply({ status: "ok" }, 502))
      .mockImplementation(() => reply({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus());
    await advance(20_000);
    expect(result.current.status).toBe("ok");
  });

  it("aborts a hung request after about 10 s and retries", async () => {
    const fetchMock = vi.fn(hungFetch);
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useBackendStatus());
    await advance(9_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await advance(7_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  });

  it("stays bounded to about 90 s even if every request hangs", async () => {
    vi.stubGlobal("fetch", vi.fn(hungFetch));
    const { result } = renderHook(() => useBackendStatus());
    await advance(80_000);
    expect(result.current.status).toBe("waking");
    await advance(10_000);
    expect(result.current.status).toBe("unavailable");
  });

  it("aborts the in-flight request and stops retrying on unmount", async () => {
    const fetchMock = vi.fn(hungFetch);
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = renderHook(() => useBackendStatus());
    const signal = fetchMock.mock.calls[0]?.[1]?.signal;
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
    await advance(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["missing", ""],
    ["without a scheme", "api.example"],
  ])("is unavailable immediately when the API URL is %s", async (_n, value) => {
    vi.stubEnv("VITE_API_BASE_URL", value);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useBackendStatus());
    await advance(0);
    expect(result.current.status).toBe("unavailable");
    expect(errorSpy).toHaveBeenCalled();
    errorSpy.mockClear();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("retry() restarts the check with a fresh window", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.reject(new TypeError("down")));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus());
    await advance(95_000);
    expect(result.current.status).toBe("unavailable");

    fetchMock.mockImplementation(() => reply({ status: "ok" }));
    act(() => result.current.retry());
    expect(result.current.status).toBe("checking");
    await advance(0);
    expect(result.current.status).toBe("ok");
  });
});
