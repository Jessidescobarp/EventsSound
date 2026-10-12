import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadCatalog,
  MAX_CATALOG_ENTRIES,
  parseItems,
  parsePackages,
} from "./catalog";
import { ApiError } from "./client";

const item = (over: Record<string, unknown> = {}) => ({
  code: "sound_speaker_active_15",
  name: "Parlante activo 15 pulgadas",
  category: "sound",
  stock_quantity: 8,
  unit_price_cop: 120000,
  ...over,
});

const pkg = (over: Record<string, unknown> = {}) => ({
  code: "pkg_basic_party",
  name: "Fiesta Basica",
  discount_bps: 1000,
  base_price_cop: 540000,
  items: [{ item_code: "sound_speaker_active_15", quantity: 2 }],
  ...over,
});

describe("parseItems", () => {
  it("accepts the contract shape", () => {
    expect(parseItems({ items: [item()] })).toEqual([item()]);
  });

  it("accepts an empty list", () => {
    expect(parseItems({ items: [] })).toEqual([]);
  });

  it("drops unknown extra keys instead of passing them on", () => {
    const [parsed] = parseItems({ items: [item({ id: 7, secret: "x" })] });
    expect(parsed).not.toHaveProperty("id");
    expect(parsed).not.toHaveProperty("secret");
  });

  it.each([
    ["null body", null],
    ["array body", []],
    ["string body", "x"],
    ["missing items", {}],
    ["items not an array", { items: {} }],
    ["null element", { items: [null] }],
    ["missing code", { items: [item({ code: undefined })] }],
    ["empty code", { items: [item({ code: "" })] }],
    ["numeric name", { items: [item({ name: 5 })] }],
    ["overlong name", { items: [item({ name: "a".repeat(201) })] }],
    ["missing category", { items: [item({ category: undefined })] }],
    ["float price", { items: [item({ unit_price_cop: 10.5 })] }],
    ["string price", { items: [item({ unit_price_cop: "10" })] }],
    ["negative price", { items: [item({ unit_price_cop: -1 })] }],
    ["unsafe integer price", { items: [item({ unit_price_cop: 2 ** 60 })] }],
    ["NaN stock", { items: [item({ stock_quantity: Number.NaN })] }],
    ["negative stock", { items: [item({ stock_quantity: -1 })] }],
  ])("rejects %s", (_name, body) => {
    expect(() => parseItems(body)).toThrow();
  });

  it("rejects more entries than the cap", () => {
    const many = Array.from({ length: MAX_CATALOG_ENTRIES + 1 }, (_, i) =>
      item({ code: `c${i}` }),
    );
    expect(() => parseItems({ items: many })).toThrow();
  });

  it("rejects duplicate codes", () => {
    expect(() => parseItems({ items: [item(), item()] })).toThrow();
  });
});

describe("parsePackages", () => {
  it("accepts the contract shape and an empty list", () => {
    expect(parsePackages({ packages: [pkg()] })).toEqual([pkg()]);
    expect(parsePackages({ packages: [] })).toEqual([]);
  });

  it.each([
    ["missing packages", {}],
    ["discount above 100%", { packages: [pkg({ discount_bps: 10001 })] }],
    ["negative discount", { packages: [pkg({ discount_bps: -1 })] }],
    ["float discount", { packages: [pkg({ discount_bps: 10.5 })] }],
    ["negative base price", { packages: [pkg({ base_price_cop: -5 })] }],
    ["items not an array", { packages: [pkg({ items: "x" })] }],
    ["member without code", { packages: [pkg({ items: [{ quantity: 1 }] })] }],
    ["member with zero quantity", { packages: [pkg({ items: [{ item_code: "a", quantity: 0 }] })] }],
    ["member with float quantity", { packages: [pkg({ items: [{ item_code: "a", quantity: 1.5 }] })] }],
  ])("rejects %s", (_name, body) => {
    expect(() => parsePackages(body)).toThrow();
  });

  it("accepts a package without members (display-only)", () => {
    expect(parsePackages({ packages: [pkg({ items: [] })] })).toHaveLength(1);
  });
});

describe("loadCatalog", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  });

  const reply = (body: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(body), { status }));

  it("fetches both endpoints and returns typed data", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) =>
      String(input).endsWith("/catalog/items")
        ? reply({ items: [item()] })
        : reply({ packages: [pkg()] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const data = await loadCatalog();
    expect(data.items).toHaveLength(1);
    expect(data.packages).toHaveLength(1);
    expect(fetchMock.mock.calls.map((c) => String(c[0])).sort()).toEqual([
      "https://api.example/catalog/items",
      "https://api.example/catalog/packages",
    ]);
  });

  it("fails with the error of a failing endpoint (404)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply({ detail: "Not Found" }, 404)));
    const error = await loadCatalog().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("not_found");
  });

  it("fails with invalid_response when a payload breaks the contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        String(input).endsWith("/catalog/items")
          ? reply({ items: [item({ unit_price_cop: "x" })] })
          : reply({ packages: [] }),
      ),
    );
    const error = await loadCatalog().catch((e: unknown) => e);
    expect((error as ApiError).code).toBe("invalid_response");
  });
});
