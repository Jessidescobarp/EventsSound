import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import {
  classifyRecordsError,
  fetchAdminBookings,
  fetchAdminQuotes,
  fetchMyQuotes,
  parseBookingPage,
  parseQuotePage,
} from "./records";

const QUOTE = {
  version: 1,
  currency: "COP",
  rental_days: 1,
  lines: [
    { kind: "item", code: "sound_x", label: "Parlante", quantity: 2, periods: 1, unit_amount: 80000, rate_bps: null, basis: null, amount: 160000 },
  ],
  subtotal: 160000,
  total: 160000,
};
const RECORD = {
  id: "q-1",
  created_at: "2026-10-15T12:00:00+00:00",
  registered: false,
  event_type: "wedding",
  event_start: "2026-10-31T17:00:00-05:00",
  event_end: "2026-10-31T22:00:00-05:00",
  guest_count: 100,
  total_cop: 160000,
  available: null,
  quote: QUOTE,
  event_request: { anything: true },
};
const page = (items: unknown[], extra = {}) => ({ items, total: items.length, limit: 10, offset: 0, ...extra });

describe("quote pages", () => {
  it("parses a page and drops the fields the UI does not use", () => {
    const parsed = parseQuotePage(page([RECORD]));

    expect(parsed.items[0]).toMatchObject({ id: "q-1", total_cop: 160000, quote: { total: 160000 } });
    expect(parsed.items[0]).not.toHaveProperty("event_request");
  });

  it("keeps a row whose stored breakdown no longer parses, with a null quote", () => {
    const parsed = parseQuotePage(page([{ ...RECORD, quote: { legacy_field: 1 } }]));

    expect(parsed.items).toHaveLength(1);
    expect(parsed.items[0]?.quote).toBeNull();
  });

  it.each([
    [page([RECORD], { limit: 0 })],
    [page([RECORD, RECORD], { limit: 1 })],
    [page([{ ...RECORD, guest_count: 0 }])],
    [page([{ ...RECORD, registered: "yes" }])],
    [{ items: "x", total: 1, limit: 10, offset: 0 }],
  ])("rejects a malformed page: %#", (body) => {
    expect(() => parseQuotePage(body)).toThrow();
  });
});

describe("booking pages", () => {
  const booking = { booking_code: "BK-1", item_code: "sound_x", quantity: 2, starts_at: "a", ends_at: "b", status: "pending", created_at: "c" };

  it("parses bookings", () => {
    expect(parseBookingPage(page([booking])).items[0]).toEqual(booking);
  });

  it("rejects a zero quantity", () => {
    expect(() => parseBookingPage(page([{ ...booking, quantity: 0 }]))).toThrow();
  });
});

describe("fetchers", () => {
  beforeEach(() => vi.stubEnv("VITE_API_BASE_URL", "https://api.example"));
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    [fetchMyQuotes, "/me/quotes"],
    [fetchAdminQuotes, "/admin/quotes"],
  ])("asks %# with the bearer token and the paging", async (fetcher, path) => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(Response.json(page([RECORD]))));
    vi.stubGlobal("fetch", fetchMock);

    await fetcher("tok.en.x", { limit: 10, offset: 20 });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toBe(`https://api.example${path}?limit=10&offset=20`);
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok.en.x");
  });

  it("uses the bookings path for bookings", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(Response.json(page([]))));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAdminBookings("t.o.k", { limit: 5, offset: 0 });

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("https://api.example/admin/bookings?limit=5&offset=0");
  });
});

describe("classifyRecordsError", () => {
  const api = (code: ApiError["code"], status?: number) => new ApiError(code, "x", status);

  it.each([
    [api("http", 401), "unauthenticated"],
    [api("http", 403), "forbidden"],
    [api("server", 503), "unavailable"],
    [api("server", 500), "transient"],
    [api("network"), "transient"],
    [api("aborted"), "aborted"],
    [api("invalid_response"), "unexpected"],
    [new Error("x"), "unexpected"],
  ])("maps %# to its failure class", (error, expected) => {
    expect(classifyRecordsError(error)).toBe(expected);
  });
});
