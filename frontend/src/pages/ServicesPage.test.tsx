import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CatalogItem, ServicePackage } from "../api/catalog";
import { es } from "../copy/es";
import { MOCK_ITEMS, MOCK_PACKAGES } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";
import { normalizeSpaces } from "../test/text";

type Handler = (path: string) => Response | Promise<Response>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Routes /health to ok and delegates the catalog paths to `catalog`. */
const server =
  (catalog: Handler) =>
  (input: RequestInfo | URL): Promise<Response> => {
    const path = new URL(String(input)).pathname;
    if (path === "/health") return Promise.resolve(json({ status: "ok" }));
    return Promise.resolve(catalog(path));
  };

const serve = (items: unknown, packages: unknown): Handler => (path) =>
  path === "/catalog/items" ? json(items) : json(packages);

const item = (over: Partial<CatalogItem> = {}): CatalogItem => ({
  code: "sound_a",
  name: "Parlante A",
  category: "sound",
  stock_quantity: 3,
  unit_price_cop: 120000,
  ...over,
});

const pkg = (over: Partial<ServicePackage> = {}): ServicePackage => ({
  code: "pkg_a",
  name: "Paquete A",
  discount_bps: 1050,
  base_price_cop: 240000,
  items: [{ item_code: "sound_a", quantity: 2 }],
  ...over,
});

const norm = normalizeSpaces;
/** Direct <li> children only: package cards contain a nested member list. */
const rows = (list: HTMLElement) => Array.from(list.children);
const UNAVAILABLE = es.services.unavailableTitle;
const flush = () => act(() => vi.advanceTimersByTimeAsync(0));

afterEach(() => {
  vi.useRealTimers();
});

describe("catalog page: success", () => {
  it("lists packages and items from the API with formatted prices", async () => {
    renderApp("/servicios", server(serve({ items: [item()] }, { packages: [pkg()] })));
    expect(await screen.findByRole("heading", { level: 2, name: es.services.packagesTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: es.services.itemsTitle })).toBeInTheDocument();

    const packages = screen.getByRole("list", { name: es.services.packagesTitle });
    const [card] = rows(packages) as HTMLElement[];
    expect(rows(packages)).toHaveLength(1);
    expect(within(card).getByRole("heading", { level: 3, name: "Paquete A" })).toBeInTheDocument();
    expect(norm(card.textContent)).toContain("$ 240.000");
    expect(card).toHaveTextContent("10,5% de descuento");
    expect(card).toHaveTextContent("2 × Parlante A");

    const items = screen.getByRole("list", { name: es.services.itemsTitle });
    const [row] = rows(items) as HTMLElement[];
    expect(rows(items)).toHaveLength(1);
    expect(within(row).getByRole("heading", { level: 3, name: "Parlante A" })).toBeInTheDocument();
    expect(norm(row.textContent)).toContain("$ 120.000");
    expect(row).toHaveTextContent("3 unidades disponibles");
    expect(row).toHaveTextContent("Sonido");
  });

  it("falls back to the code for a package member missing from the items", async () => {
    renderApp(
      "/servicios",
      server(serve({ items: [] }, { packages: [pkg({ items: [{ item_code: "ghost_code", quantity: 1 }] })] })),
    );
    expect(await screen.findByText("1 × ghost_code")).toBeInTheDocument();
  });

  it("uses the singular for one unit", async () => {
    renderApp("/servicios", server(serve({ items: [item({ stock_quantity: 1 })] }, { packages: [] })));
    expect(await screen.findByText("1 unidad disponible")).toBeInTheDocument();
  });

  it("renders the whole demo dataset", async () => {
    renderApp("/servicios", server(serve({ items: MOCK_ITEMS }, { packages: MOCK_PACKAGES })));
    await screen.findByRole("heading", { level: 2, name: es.services.itemsTitle });
    const items = screen.getByRole("list", { name: es.services.itemsTitle });
    expect(rows(items)).toHaveLength(MOCK_ITEMS.length);
    const packages = screen.getByRole("list", { name: es.services.packagesTitle });
    expect(rows(packages)).toHaveLength(MOCK_PACKAGES.length);
  });

  it("links to the chat placeholder", async () => {
    renderApp("/servicios", server(serve({ items: [item()] }, { packages: [] })));
    const link = await screen.findByRole("link", { name: es.services.chatCtaButton });
    expect(link).toHaveAttribute("href", "/cotizar");
  });
});

describe("catalog page: category filter", () => {
  const data = {
    items: [
      item({ code: "a", name: "Parlante A", category: "sound" }),
      item({ code: "b", name: "Luz B", category: "lighting" }),
      item({ code: "c", name: "Rareza C", category: "inventada" }),
    ],
  };

  it("offers only the categories present and filters the equipment list", async () => {
    renderApp("/servicios", server(serve(data, { packages: [] })));
    const select = await screen.findByRole("combobox", { name: es.services.categoryFilterLabel });
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual([
      es.services.categoryAll,
      "Sonido",
      "Iluminación",
      es.services.categoryFallback,
    ]);

    fireEvent.change(select, { target: { value: "lighting" } });
    const list = screen.getByRole("list", { name: es.services.itemsTitle });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(within(list).getByRole("heading", { name: "Luz B" })).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "" } });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  });

  it("shows unknown categories as 'Otros', never the raw value", async () => {
    renderApp("/servicios", server(serve(data, { packages: [] })));
    const list = await screen.findByRole("list", { name: es.services.itemsTitle });
    const row = within(list).getByRole("heading", { name: "Rareza C" }).closest("li")!;
    expect(row).toHaveTextContent(es.services.categoryFallback);
    expect(row).not.toHaveTextContent("inventada");
  });
});

describe("catalog page: loading", () => {
  it("shows a loading status while the catalog is pending", async () => {
    vi.useFakeTimers();
    renderApp("/servicios", server(() => new Promise<Response>(() => {})));
    await flush();
    expect(screen.getByText(es.services.loading)).toBeInTheDocument();
    expect(screen.queryByText(UNAVAILABLE)).toBeNull();
  });
});

describe("catalog page: empty", () => {
  it("shows friendly empty messages for both lists", async () => {
    renderApp("/servicios", server(serve({ items: [] }, { packages: [] })));
    expect(await screen.findByText(es.services.emptyItems)).toBeInTheDocument();
    expect(screen.getByText(es.services.emptyPackages)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByText(UNAVAILABLE)).toBeNull();
  });

  it("shows the empty message only for the list that is empty", async () => {
    renderApp("/servicios", server(serve({ items: [item()] }, { packages: [] })));
    expect(await screen.findByText(es.services.emptyPackages)).toBeInTheDocument();
    expect(screen.queryByText(es.services.emptyItems)).toBeNull();
  });
});

describe("catalog page: failures never crash the page", () => {
  const pageStillWorks = () => {
    expect(screen.getByRole("heading", { level: 1, name: es.services.title })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: es.a11y.mainNav })).toBeInTheDocument();
  };

  it("shows the coming-soon message on 404 without retrying", async () => {
    const handler = vi.fn<Handler>(() => json({ detail: "Not Found" }, 404));
    renderApp("/servicios", server(handler));
    expect(await screen.findByText(UNAVAILABLE)).toBeInTheDocument();
    expect(screen.getByText(es.services.unavailableBody)).toBeInTheDocument();
    pageStillWorks();
    expect(handler).toHaveBeenCalledTimes(2); // items + packages, one attempt each
    expect(screen.queryByRole("list", { name: es.services.itemsTitle })).toBeNull();
  });

  it.each([
    ["500", () => json({ detail: "x" }, 500)],
    ["503 catalog_unavailable", () => json({ detail: "catalog_unavailable" }, 503)],
    ["network error", () => Promise.reject(new TypeError("down"))],
  ])("retries a transient failure (%s) a bounded number of times then shows the message", async (_n, handler) => {
    vi.useFakeTimers();
    const spy = vi.fn<Handler>(handler as Handler);
    renderApp("/servicios", server(spy));
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByText(UNAVAILABLE)).toBeInTheDocument();
    pageStillWorks();
    const calls = spy.mock.calls.length;
    expect(calls).toBeGreaterThanOrEqual(3);
    expect(calls).toBeLessThanOrEqual(6); // 1 + 2 retries, per endpoint
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    expect(spy.mock.calls.length).toBe(calls);
  });

  it("shows the message for a hung request (timeout)", async () => {
    vi.useFakeTimers();
    renderApp("/servicios", (input, init) =>
      new URL(String(input)).pathname === "/health"
        ? Promise.resolve(json({ status: "ok" }))
        : new Promise<Response>((_res, reject) =>
            init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))),
          ),
    );
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(screen.getByText(UNAVAILABLE)).toBeInTheDocument();
  });

  it.each([
    ["wrong field type", { items: [item({ unit_price_cop: "10" as unknown as number })] }, { packages: [] }],
    ["missing items key", {}, { packages: [] }],
    ["items is not an array", { items: "x" }, { packages: [] }],
    ["null body", null, { packages: [] }],
    ["bad packages payload", { items: [] }, { packages: [{ code: "p" }] }],
    ["too many entries", { items: Array.from({ length: 501 }, (_, i) => item({ code: `c${i}` })) }, { packages: [] }],
  ])("shows the message for malformed data: %s", async (_n, items, packages) => {
    renderApp("/servicios", server(serve(items, packages)));
    expect(await screen.findByText(UNAVAILABLE)).toBeInTheDocument();
    pageStillWorks();
  });

  it("shows the message when the body is not JSON", async () => {
    renderApp("/servicios", server(() => new Response("<html>gateway</html>")));
    expect(await screen.findByText(UNAVAILABLE)).toBeInTheDocument();
  });

  it("refuses a huge payload", async () => {
    const big = "x".repeat(1_100_000);
    renderApp("/servicios", server(() => new Response(JSON.stringify({ items: [], pad: big }))));
    expect(await screen.findByText(UNAVAILABLE)).toBeInTheDocument();
  });

  it("retry button reloads and shows the catalog once it exists", async () => {
    let live = false;
    const handler: Handler = (path) =>
      !live
        ? json({ detail: "Not Found" }, 404)
        : path === "/catalog/items"
          ? json({ items: [item()] })
          : json({ packages: [] });
    renderApp("/servicios", server(handler));
    await screen.findByText(UNAVAILABLE);

    live = true;
    fireEvent.click(screen.getByRole("button", { name: es.common.retry }));
    expect(await screen.findByText("Parlante A")).toBeInTheDocument();
    expect(screen.queryByText(UNAVAILABLE)).toBeNull();
  });

  it("renders API text as inert text, never as HTML", async () => {
    const evil = '<img src=x onerror="alert(1)"><script>alert(1)</script>';
    const { container } = renderApp(
      "/servicios",
      server(serve({ items: [item({ name: evil })] }, { packages: [pkg({ name: evil })] })),
    );
    await screen.findAllByText(evil);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
  });
});

describe("catalog page: robustness of rendering", () => {
  it("lets very long names wrap instead of overflowing", async () => {
    const long = "Superlargo".repeat(20);
    renderApp(
      "/servicios",
      server(serve({ items: [item({ name: long })] }, { packages: [pkg({ name: long })] })),
    );
    const headings = await screen.findAllByRole("heading", { level: 3, name: long });
    expect(headings).toHaveLength(2);
    for (const heading of headings) expect(heading.className).toContain("break-words");
  });

  it.each(["constructor", "__proto__", "toString", "hasOwnProperty"])(
    "treats the inherited-property category %j as 'Otros' without crashing",
    async (category) => {
      renderApp("/servicios", server(serve({ items: [item({ category })] }, { packages: [] })));
      const list = await screen.findByRole("list", { name: es.services.itemsTitle });
      expect(list).toHaveTextContent(es.services.categoryFallback);
      const select = screen.getByRole("combobox", { name: es.services.categoryFilterLabel });
      const options = within(select).getAllByRole("option").map((o) => o.textContent);
      expect(options).toEqual([es.services.categoryAll, es.services.categoryFallback]);
    },
  );

  it("shows the discount badge only when the discount is above zero", async () => {
    renderApp(
      "/servicios",
      server(
        serve(
          { items: [item()] },
          {
            packages: [
              pkg({ code: "p0", name: "Sin descuento", discount_bps: 0 }),
              pkg({ code: "p1", name: "Con descuento", discount_bps: 1 }),
            ],
          },
        ),
      ),
    );
    const packages = await screen.findByRole("list", { name: es.services.packagesTitle });
    const [none, some] = rows(packages);
    expect(none).not.toHaveTextContent("de descuento");
    expect(some).toHaveTextContent("0,01% de descuento");
  });
});
