import { apiFetch } from "./client";

/**
 * Catalog contract: openspec quote-domain-core / specs/catalog-api (GET /catalog/items
 * and GET /catalog/packages). The API is not deployed yet; the page is built against
 * this contract and the fake API in src/mocks.
 */
export interface CatalogItem {
  code: string;
  name: string;
  category: string;
  stock_quantity: number;
  unit_price_cop: number;
}

export interface PackageMember {
  item_code: string;
  quantity: number;
}

export interface ServicePackage {
  code: string;
  name: string;
  discount_bps: number;
  base_price_cop: number;
  items: PackageMember[];
}

export interface Catalog {
  items: CatalogItem[];
  packages: ServicePackage[];
}

/** The real catalog has tens of rows (cap 40/6); anything above this is not our API. */
export const MAX_CATALOG_ENTRIES = 500;
const MAX_TEXT = 200;

// ---- runtime guards: the JSON is untrusted, so every field is checked ----

type Obj = Record<string, unknown>;

function asObject(value: unknown, what: string): Obj {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${what} must be an object`);
  }
  return value as Obj;
}

function text(o: Obj, key: string): string {
  const v = o[key];
  if (typeof v !== "string" || v.length === 0 || v.length > MAX_TEXT) {
    throw new Error(`${key} must be a non-empty string`);
  }
  return v;
}

function int(o: Obj, key: string, min: number, max = Number.MAX_SAFE_INTEGER): number {
  const v = o[key];
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < min || v > max) {
    throw new Error(`${key} must be an integer in [${min}, ${max}]`);
  }
  return v;
}

function list(o: Obj, key: string): unknown[] {
  const v = o[key];
  if (!Array.isArray(v) || v.length > MAX_CATALOG_ENTRIES) {
    throw new Error(`${key} must be an array of at most ${MAX_CATALOG_ENTRIES}`);
  }
  return v;
}

function assertUnique(codes: string[], what: string): void {
  if (new Set(codes).size !== codes.length) throw new Error(`duplicate ${what} code`);
}

export function parseItems(json: unknown): CatalogItem[] {
  const items = list(asObject(json, "body"), "items").map((raw): CatalogItem => {
    const o = asObject(raw, "item");
    return {
      code: text(o, "code"),
      name: text(o, "name"),
      category: text(o, "category"),
      stock_quantity: int(o, "stock_quantity", 0),
      unit_price_cop: int(o, "unit_price_cop", 0),
    };
  });
  assertUnique(items.map((i) => i.code), "item");
  return items;
}

export function parsePackages(json: unknown): ServicePackage[] {
  const packages = list(asObject(json, "body"), "packages").map((raw): ServicePackage => {
    const o = asObject(raw, "package");
    return {
      code: text(o, "code"),
      name: text(o, "name"),
      discount_bps: int(o, "discount_bps", 0, 10_000),
      base_price_cop: int(o, "base_price_cop", 0),
      items: list(o, "items").map((member): PackageMember => {
        const m = asObject(member, "package member");
        return { item_code: text(m, "item_code"), quantity: int(m, "quantity", 1) };
      }),
    };
  });
  assertUnique(packages.map((p) => p.code), "package");
  return packages;
}

/** Loads both lists; fails with the ApiError of whichever request fails first. */
export async function loadCatalog(signal?: AbortSignal): Promise<Catalog> {
  const [items, packages] = await Promise.all([
    apiFetch("/catalog/items", { parse: parseItems, signal }),
    apiFetch("/catalog/packages", { parse: parsePackages, signal }),
  ]);
  return { items, packages };
}
