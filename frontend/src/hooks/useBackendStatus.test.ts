import { act, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { useBackendStatus } from "./useBackendStatus";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

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

describe("useBackendStatus: shared with API calls, visibility, StrictMode, deadline", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(document, "hidden");
  });

  const setHidden = (hidden: boolean) => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    document.dispatchEvent(new Event("visibilitychange"));
  };

  it("clears a stale unavailable state when any API call succeeds", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.reject(new TypeError("down")));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus());
    await advance(95_000);
    expect(result.current.status).toBe("unavailable");

    fetchMock.mockImplementation(() => reply({ ok: 1 }));
    await act(() => apiFetch("/catalog/items", { parse: (j) => j }));
    expect(result.current.status).toBe("ok");
  });

  it("stops polling health once another API call proved the backend is up", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) =>
      String(input).endsWith("/health") ? Promise.reject(new TypeError("cold")) : reply({ ok: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus());
    await advance(100);
    expect(result.current.status).toBe("waking");
    await act(() => apiFetch("/catalog/items", { parse: (j) => j }));
    expect(result.current.status).toBe("ok");
    const calls = fetchMock.mock.calls.length;
    await advance(60_000);
    expect(fetchMock.mock.calls.length).toBe(calls);
    expect(result.current.status).toBe("ok");
  });

  it("does not spin while the tab is hidden and resumes when it is visible again", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.reject(new TypeError("cold")));
    vi.stubGlobal("fetch", fetchMock);
    setHidden(true);
    const { result } = renderHook(() => useBackendStatus());
    await advance(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1); // the first probe only
    expect(result.current.status).toBe("waking");

    setHidden(false);
    await advance(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await advance(10_000);
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(4);
  });

  it("gives a fresh window when the tab comes back after the old one expired", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.reject(new TypeError("cold")));
    vi.stubGlobal("fetch", fetchMock);
    setHidden(true);
    const { result } = renderHook(() => useBackendStatus());
    await advance(200_000);
    fetchMock.mockImplementation(() => reply({ status: "ok" }));
    setHidden(false);
    await advance(0);
    expect(result.current.status).toBe("ok");
  });

  it("does not resume anything on visibility changes when it was never paused", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => reply({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useBackendStatus());
    await advance(0);
    setHidden(true);
    setHidden(false);
    await advance(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("survives StrictMode double effects: settles to ok and leaves nothing running", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => reply({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    const { result, unmount } = renderHook(() => useBackendStatus(), { wrapper: StrictMode });
    await advance(0);
    expect(result.current.status).toBe("ok");
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(2);
    unmount();
    const calls = fetchMock.mock.calls.length;
    await advance(120_000);
    expect(fetchMock.mock.calls.length).toBe(calls);
  });

  it("StrictMode with a failing backend still ends unavailable within the window", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("down"))));
    const { result } = renderHook(() => useBackendStatus(), { wrapper: StrictMode });
    await advance(100_000);
    expect(result.current.status).toBe("unavailable");
  });

  it("decides unavailable exactly when the next probe would pass the deadline", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.reject(new TypeError("down")));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus());
    await advance(84_999);
    expect(result.current.status).toBe("waking");
    await advance(1);
    expect(result.current.status).toBe("unavailable");
    expect(fetchMock).toHaveBeenCalledTimes(18); // probes at 0, 5 s ... 85 s
  });
});
