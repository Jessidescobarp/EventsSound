import { fireEvent, screen, within } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { es } from "../copy/es";
import { MOCK_ITEMS, MOCK_PACKAGES } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";
import { advanceInSteps } from "../test/timers";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Backend that is asleep (503 everywhere) until `wakesAtMs`, then healthy. */
function sleepingBackend(wakesAtMs: number, { healthWakesAtMs = wakesAtMs } = {}) {
  const start = Date.now();
  const calls: string[] = [];
  const impl = (input: RequestInfo | URL): Promise<Response> => {
    const path = new URL(String(input)).pathname;
    calls.push(path);
    const elapsed = Date.now() - start;
    if (path === "/health") {
      return Promise.resolve(elapsed >= healthWakesAtMs ? json({ status: "ok" }) : json({}, 503));
    }
    if (elapsed < wakesAtMs) return Promise.resolve(json({ detail: "waking" }, 503));
    return Promise.resolve(
      path === "/catalog/items" ? json({ items: MOCK_ITEMS }) : json({ packages: MOCK_PACKAGES }),
    );
  };
  return { impl: impl as typeof fetch, calls };
}

const advance = (ms: number) => advanceInSteps(ms);
const banner = () => screen.getAllByRole("status")[0]!;

describe("catalog page during a cold start", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits while the server wakes, never flashing the unavailable message, then loads", async () => {
    const { impl } = sleepingBackend(60_000);
    renderApp("/servicios", impl);

    for (const step of [1_000, 9_000, 20_000, 25_000]) {
      await advance(step); // cumulative: 1 s, 10 s, 30 s, 55 s
      expect(screen.queryByText(es.services.unavailableTitle)).toBeNull();
      expect(screen.getByText(/Cargando el catálogo|Esperando al servidor/)).toBeInTheDocument();
    }
    expect(screen.getByText(es.services.waiting)).toBeInTheDocument();
    expect(banner()).toHaveTextContent(es.banners.wakingTitle);

    await advance(20_000); // the backend woke at 60 s; the next probe sees it
    expect(screen.getByRole("heading", { level: 2, name: es.services.itemsTitle })).toBeInTheDocument();
    expect(screen.queryByText(es.services.unavailableTitle)).toBeNull();
    expect(banner()).toBeEmptyDOMElement();
  });

  it("reloads by itself when the backend comes up (health first, API after)", async () => {
    const { impl } = sleepingBackend(0, { healthWakesAtMs: 20_000 });
    // API is awake but health lags: still the page must not give up at 4 s
    renderApp("/servicios", impl);
    await advance(30_000);
    expect(screen.getByRole("heading", { level: 2, name: es.services.itemsTitle })).toBeInTheDocument();
  });

  it("gives up with the friendly message once the 90 s window expires", async () => {
    const { impl, calls } = sleepingBackend(Number.POSITIVE_INFINITY);
    renderApp("/servicios", impl);
    await advance(80_000);
    expect(screen.queryByText(es.services.unavailableTitle)).toBeNull();
    await advance(15_000);
    expect(screen.getByText(es.services.unavailableTitle)).toBeInTheDocument();
    expect(banner()).toHaveTextContent(es.banners.unavailableTitle);

    const total = calls.length;
    await advance(300_000);
    expect(calls.length).toBe(total); // bounded: nothing keeps polling
  });

  it("a successful catalog retry clears a stale unavailable banner", async () => {
    let awake = false;
    const impl = ((input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      if (path === "/health") return Promise.resolve(json({}, 503)); // health never recovers
      if (!awake) return Promise.resolve(json({}, 503));
      return Promise.resolve(
        path === "/catalog/items" ? json({ items: MOCK_ITEMS }) : json({ packages: MOCK_PACKAGES }),
      );
    }) as typeof fetch;
    renderApp("/servicios", impl);
    await advance(95_000);
    expect(banner()).toHaveTextContent(es.banners.unavailableTitle);

    awake = true;
    const pageRetry = within(screen.getByRole("main")).getByRole("button", { name: es.common.retry });
    fireEvent.click(pageRetry);
    await advance(1_000);
    expect(screen.getByRole("heading", { level: 2, name: es.services.itemsTitle })).toBeInTheDocument();
    expect(banner()).toBeEmptyDOMElement();
  });

  it("when health is fine but the catalog keeps failing, retries stay bounded", async () => {
    const calls: string[] = [];
    const impl = ((input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      calls.push(path);
      return Promise.resolve(path === "/health" ? json({ status: "ok" }) : json({}, 503));
    }) as typeof fetch;
    renderApp("/servicios", impl);
    await advance(60_000);
    expect(screen.getByText(es.services.unavailableTitle)).toBeInTheDocument();
    const catalogCalls = calls.filter((c) => c !== "/health").length;
    expect(catalogCalls).toBeLessThanOrEqual(18); // (1 + 2 retries) x (1 + 2 reloads) x 2 endpoints
    await advance(300_000);
    expect(calls.filter((c) => c !== "/health").length).toBe(catalogCalls);
  });

  it("does not poll after unmount", async () => {
    const { impl, calls } = sleepingBackend(Number.POSITIVE_INFINITY);
    const { unmount } = renderApp("/servicios", impl);
    await advance(7_000);
    unmount();
    const total = calls.length;
    await advance(200_000);
    expect(calls.length).toBe(total);
  });

  it("works under StrictMode double effects", async () => {
    const { impl } = sleepingBackend(0);
    const { unmount } = renderApp("/servicios", impl, StrictMode);
    await advance(5_000);
    expect(screen.getByRole("heading", { level: 2, name: es.services.itemsTitle })).toBeInTheDocument();
    unmount();
  });
});
