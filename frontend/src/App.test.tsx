import { readFileSync } from "node:fs";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("App", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the heading and a Spanish document", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "EventsSound" }),
    ).toBeInTheDocument();
    // jsdom does not load index.html, so assert the served document directly.
    const html = new DOMParser().parseFromString(
      readFileSync("index.html", "utf8"),
      "text/html",
    );
    expect(html.documentElement.lang).toBe("es");
  });

  it("shows the loading message while the request is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<App />);
    expect(
      screen.getByText("Cargando estado del servicio..."),
    ).toBeInTheDocument();
  });

  it("requests health at the configured base URL and shows ok", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => json({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    expect(await screen.findByText("Servicio operativo")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/health");
  });

  describe("when the backend stays down", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it.each([
      ["rejects", () => Promise.reject(new TypeError("network"))],
      ["returns 503", () => json({ status: "down" }, 503)],
    ])("shows unavailable after the retry window when fetch %s", async (_n, impl) => {
      const fetchMock = vi.fn(impl);
      vi.stubGlobal("fetch", fetchMock);
      render(<App />);

      await act(() => vi.advanceTimersByTimeAsync(30_000));
      expect(
        screen.getByText("Cargando estado del servicio..."),
      ).toBeInTheDocument();
      expect(fetchMock.mock.calls.length).toBeGreaterThan(1);

      await act(() => vi.advanceTimersByTimeAsync(70_000));
      expect(screen.getByText("Servicio no disponible")).toBeInTheDocument();
    });

    it("recovers when the backend wakes up within the window", async () => {
      const fetchMock = vi
        .fn()
        .mockImplementationOnce(() => Promise.reject(new TypeError("cold")))
        .mockImplementationOnce(() => json({ status: "ok" }, 502))
        .mockImplementation(() => json({ status: "ok" }));
      vi.stubGlobal("fetch", fetchMock);
      render(<App />);

      await act(() => vi.advanceTimersByTimeAsync(20_000));
      expect(screen.getByText("Servicio operativo")).toBeInTheDocument();
    });

    it("shows unavailable immediately when the API URL is not configured", async () => {
      vi.stubEnv("VITE_API_BASE_URL", "");
      vi.stubGlobal("fetch", vi.fn());
      vi.spyOn(console, "error").mockImplementation(() => {});
      render(<App />);
      await act(() => vi.advanceTimersByTimeAsync(0));
      expect(screen.getByText("Servicio no disponible")).toBeInTheDocument();
      expect(fetch).not.toHaveBeenCalled();
    });
  });
});
