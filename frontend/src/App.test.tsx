import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

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

const LOADING = "Cargando estado del servicio...";

describe("App", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the heading and a Spanish document", () => {
    vi.stubGlobal("fetch", vi.fn(hungFetch));
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "EventSoundDR" }),
    ).toBeInTheDocument();
    // jsdom does not load index.html, so assert the served document directly.
    const html = new DOMParser().parseFromString(
      readFileSync(resolve(import.meta.dirname, "../index.html"), "utf8"),
      "text/html",
    );
    expect(html.documentElement.lang).toBe("es");
    expect(html.title).toBe("EventSoundDR");
  });

  it("shows the loading message while the request is pending", () => {
    vi.stubGlobal("fetch", vi.fn(hungFetch));
    render(<App />);
    expect(screen.getByText(LOADING)).toBeInTheDocument();
  });

  it("requests health at the configured base URL and shows ok", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => reply({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    expect(await screen.findByText("Servicio operativo")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/health");
  });

  describe("with fake timers", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it.each([
      ["rejects", () => Promise.reject(new TypeError("network"))],
      ["returns 503", () => reply({ status: "down" }, 503)],
    ])("shows unavailable after the retry window when fetch %s", async (_n, impl) => {
      const fetchMock = vi.fn(impl);
      vi.stubGlobal("fetch", fetchMock);
      render(<App />);

      await act(() => vi.advanceTimersByTimeAsync(30_000));
      expect(screen.getByText(LOADING)).toBeInTheDocument();
      expect(fetchMock.mock.calls.length).toBeGreaterThan(1);

      await act(() => vi.advanceTimersByTimeAsync(70_000));
      expect(screen.getByText("Servicio no disponible")).toBeInTheDocument();
    });

    it("recovers when the backend wakes up within the window", async () => {
      const fetchMock = vi
        .fn()
        .mockImplementationOnce(() => Promise.reject(new TypeError("cold")))
        .mockImplementationOnce(() => reply({ status: "ok" }, 502))
        .mockImplementation(() => reply({ status: "ok" }));
      vi.stubGlobal("fetch", fetchMock);
      render(<App />);

      await act(() => vi.advanceTimersByTimeAsync(20_000));
      expect(screen.getByText("Servicio operativo")).toBeInTheDocument();
    });

    it("aborts a hung request after about 10 s and retries", async () => {
      const fetchMock = vi.fn(hungFetch);
      vi.stubGlobal("fetch", fetchMock);
      render(<App />);

      await act(() => vi.advanceTimersByTimeAsync(9_000));
      expect(fetchMock).toHaveBeenCalledTimes(1);
      await act(() => vi.advanceTimersByTimeAsync(7_000));
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    });

    it("stays bounded to about 90 s even if every request hangs", async () => {
      vi.stubGlobal("fetch", vi.fn(hungFetch));
      render(<App />);

      await act(() => vi.advanceTimersByTimeAsync(80_000));
      expect(screen.getByText(LOADING)).toBeInTheDocument();
      await act(() => vi.advanceTimersByTimeAsync(10_000));
      expect(screen.getByText("Servicio no disponible")).toBeInTheDocument();
    });

    it("aborts the in-flight request and stops retrying on unmount", async () => {
      const fetchMock = vi.fn(hungFetch);
      vi.stubGlobal("fetch", fetchMock);
      const { unmount } = render(<App />);
      const signal = fetchMock.mock.calls[0]?.[1]?.signal;
      expect(signal?.aborted).toBe(false);

      unmount();
      expect(signal?.aborted).toBe(true);
      await act(() => vi.advanceTimersByTimeAsync(60_000));
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it.each([
      ["missing", ""],
      ["without a scheme", "api.example"],
    ])("shows unavailable immediately when the API URL is %s", async (_n, value) => {
      vi.stubEnv("VITE_API_BASE_URL", value);
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      render(<App />);
      await act(() => vi.advanceTimersByTimeAsync(0));
      expect(screen.getByText("Servicio no disponible")).toBeInTheDocument();
      expect(errorSpy).toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });
});
