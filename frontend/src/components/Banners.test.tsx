import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { es } from "../copy/es";
import { renderApp } from "../test/renderApp";
import { DemoBanner } from "./DemoBanner";
import { WarmupBanner } from "./WarmupBanner";

describe("DemoBanner", () => {
  it("is shown, as a note, when mocks are on", () => {
    vi.stubEnv("VITE_USE_MOCKS", "true");
    render(<DemoBanner />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(es.banners.demoTitle);
  });

  it.each(["", "false", "1"])("is absent when VITE_USE_MOCKS is %j", (value) => {
    vi.stubEnv("VITE_USE_MOCKS", value);
    render(<DemoBanner />);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("is absent when the variable is not defined at all", () => {
    render(<DemoBanner />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("DemoBanner in the app", () => {
  it.each(["/", "/quienes-somos", "/portafolio", "/servicios", "/cotizar", "/nada"])(
    "is visible on %s when mocks are on",
    async (path) => {
      vi.stubEnv("VITE_USE_MOCKS", "true");
      renderApp(path);
      expect(await screen.findByRole("note")).toHaveTextContent(es.banners.demoTitle);
    },
  );

  it("is not rendered anywhere when mocks are off", async () => {
    vi.stubEnv("VITE_USE_MOCKS", "false");
    renderApp("/servicios");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.queryByText(es.banners.demoTitle)).toBeNull();
  });
});

describe("WarmupBanner", () => {
  it("keeps an empty polite live region while checking or ok", () => {
    const { rerender } = render(<WarmupBanner status="checking" onRetry={() => {}} />);
    const region = screen.getByRole("status");
    expect(region).toBeEmptyDOMElement();
    rerender(<WarmupBanner status="ok" onRetry={() => {}} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("announces the waking state without a retry button", () => {
    render(<WarmupBanner status="waking" onRetry={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent(es.banners.wakingTitle);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers a retry button when unavailable", () => {
    const onRetry = vi.fn();
    render(<WarmupBanner status="unavailable" onRetry={onRetry} />);
    expect(screen.getByRole("status")).toHaveTextContent(es.banners.unavailableTitle);
    fireEvent.click(screen.getByRole("button", { name: es.common.retry }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("warm-up banner in the app", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows waking while the server is cold, then unavailable, then retries", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(() => Promise.reject(new TypeError("cold")));
    renderApp("/", fetchImpl as unknown as typeof fetch);

    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(screen.getByRole("status")).toHaveTextContent(es.banners.wakingTitle);

    await act(() => vi.advanceTimersByTimeAsync(95_000));
    expect(screen.getByRole("status")).toHaveTextContent(es.banners.unavailableTitle);

    const calls = fetchImpl.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: es.common.retry }));
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(fetchImpl.mock.calls.length).toBeGreaterThan(calls);
    expect(screen.getByRole("status")).toHaveTextContent(es.banners.wakingTitle);
  });

  it("shows nothing when the server answers", async () => {
    renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    await act(async () => {});
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});
