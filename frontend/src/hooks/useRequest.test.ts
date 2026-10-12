import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { isTransient, useRequest } from "./useRequest";

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

  it.each(["invalid_response", "http", "config", "too_large", "not_found", "aborted"] as const)(
    "never retries a %s error",
    async (code) => {
      const fn = vi.fn(async () => {
        throw new ApiError(code, "x");
      });
      renderHook(() => useRequest(fn, { retries: 5, retryDelaysMs: [100] }));
      await advance(60_000);
      expect(fn).toHaveBeenCalledTimes(1);
    },
  );

  it("isTransient is true only for network, timeout and server", () => {
    const codes = ["config", "network", "timeout", "aborted", "not_found", "server", "http", "invalid_response", "too_large"] as const;
    const transient = codes.filter((code) => isTransient(new ApiError(code, "x")));
    expect(transient).toEqual(["network", "timeout", "server"]);
  });

  describe("late results never overwrite newer state", () => {
    const deferred = <T,>() => {
      let resolve!: (value: T) => void;
      let reject!: (reason: unknown) => void;
      const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
      });
      return { promise, resolve, reject };
    };

    it("a request that resolves after reload() is ignored", async () => {
      const first = deferred<string>();
      const second = deferred<string>();
      const fn = vi
        .fn<(signal: AbortSignal) => Promise<string>>()
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise);
      const { result } = renderHook(() => useRequest(fn));
      act(() => result.current.reload());
      second.resolve("new");
      await advance(0);
      expect(result.current.state).toEqual({ status: "success", data: "new" });
      first.resolve("old");
      await advance(0);
      expect(result.current.state).toEqual({ status: "success", data: "new" });
    });

    it("a request that fails after reload() is ignored", async () => {
      const first = deferred<string>();
      const fn = vi
        .fn<(signal: AbortSignal) => Promise<string>>()
        .mockReturnValueOnce(first.promise)
        .mockResolvedValue("new");
      const { result } = renderHook(() => useRequest(fn));
      act(() => result.current.reload());
      await advance(0);
      expect(result.current.state).toEqual({ status: "success", data: "new" });
      first.reject(new ApiError("invalid_response", "late"));
      await advance(0);
      expect(result.current.state).toEqual({ status: "success", data: "new" });
    });

    it("a transient failure that lands after unmount schedules no retry", async () => {
      const first = deferred<string>();
      const fn = vi.fn<(signal: AbortSignal) => Promise<string>>().mockReturnValue(first.promise);
      const { unmount } = renderHook(() => useRequest(fn, { retryDelaysMs: [100] }));
      unmount();
      first.reject(new ApiError("network", "late"));
      await advance(10_000);
      expect(fn).toHaveBeenCalledTimes(1);
    });
  });
});
