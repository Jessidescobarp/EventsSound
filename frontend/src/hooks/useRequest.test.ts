import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { useRequest } from "./useRequest";

const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe("useRequest", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("goes from loading to success", async () => {
    const fn = vi.fn(async () => "datos");
    const { result } = renderHook(() => useRequest(fn));
    expect(result.current.state.status).toBe("loading");
    await advance(0);
    expect(result.current.state).toEqual({ status: "success", data: "datos" });
  });

  it("does not retry a 404 and reports the error", async () => {
    const fn = vi.fn(async () => {
      throw new ApiError("not_found", "nf", 404);
    });
    const { result } = renderHook(() => useRequest(fn));
    await advance(60_000);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(result.current.state.status).toBe("error");
    if (result.current.state.status === "error") {
      expect(result.current.state.error.code).toBe("not_found");
    }
  });

  it.each(["network", "timeout", "server"] as const)(
    "retries a %s error a bounded number of times, then fails",
    async (code) => {
      const fn = vi.fn(async () => {
        throw new ApiError(code, "x");
      });
      const { result } = renderHook(() =>
        useRequest(fn, { retries: 2, retryDelaysMs: [1_000, 3_000] }),
      );
      await advance(900);
      expect(fn).toHaveBeenCalledTimes(1);
      await advance(200);
      expect(fn).toHaveBeenCalledTimes(2);
      expect(result.current.state.status).toBe("loading");
      await advance(3_000);
      expect(fn).toHaveBeenCalledTimes(3);
      expect(result.current.state.status).toBe("error");
      await advance(60_000);
      expect(fn).toHaveBeenCalledTimes(3);
    },
  );

  it("recovers when a retry succeeds", async () => {
    const fn = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new ApiError("server", "x"))
      .mockResolvedValue("ok");
    const { result } = renderHook(() => useRequest(fn, { retryDelaysMs: [500] }));
    await advance(600);
    expect(result.current.state).toEqual({ status: "success", data: "ok" });
  });

  it("wraps an unexpected error into an ApiError instead of crashing", async () => {
    const fn = vi.fn(async () => {
      throw new Error("boom");
    });
    const { result } = renderHook(() => useRequest(fn, { retries: 0 }));
    await advance(0);
    expect(result.current.state.status).toBe("error");
    if (result.current.state.status === "error") {
      expect(result.current.state.error).toBeInstanceOf(ApiError);
    }
  });

  it("reload() returns to loading and refetches", async () => {
    const fn = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new ApiError("not_found", "nf", 404))
      .mockResolvedValue("ya");
    const { result } = renderHook(() => useRequest(fn));
    await advance(0);
    expect(result.current.state.status).toBe("error");
    act(() => result.current.reload());
    expect(result.current.state.status).toBe("loading");
    await advance(0);
    expect(result.current.state).toEqual({ status: "success", data: "ya" });
  });

  it("aborts the signal and stops retrying on unmount", async () => {
    let received: AbortSignal | undefined;
    const fn = vi.fn(async (signal: AbortSignal) => {
      received = signal;
      throw new ApiError("network", "x");
    });
    const { unmount } = renderHook(() => useRequest(fn, { retryDelaysMs: [1_000] }));
    await advance(0);
    unmount();
    expect(received?.aborted).toBe(true);
    await advance(10_000);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
