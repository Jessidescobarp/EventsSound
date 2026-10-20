import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchSecurityEvents, parseSecurityPage } from "./security";

const EVENT = { id: 7, at: "2026-10-15T12:00:00+00:00", kind: "chat_refused", client: "0123456789abcdef" };
const body = (over = {}) => ({
  items: [EVENT],
  total: 1,
  limit: 20,
  offset: 0,
  last_24h: { chat_refused: 3, login_failed: 1 },
  ...over,
});

describe("parseSecurityPage", () => {
  it("parses a page with its 24-hour counts", () => {
    expect(parseSecurityPage(body())).toEqual({
      items: [EVENT],
      total: 1,
      limit: 20,
      offset: 0,
      last_24h: { chat_refused: 3, login_failed: 1 },
    });
  });

  it("counts a kind the server leaves out as zero", () => {
    expect(parseSecurityPage(body({ last_24h: { login_failed: 2 } })).last_24h).toEqual({
      chat_refused: 0,
      login_failed: 2,
    });
  });

  it.each([
    ["unknown kind", body({ items: [{ ...EVENT, kind: "other" }] })],
    ["client that is not a 16-hex key", body({ items: [{ ...EVENT, client: "10.0.0.1" }] })],
    ["non-integer id", body({ items: [{ ...EVENT, id: "7" }] })],
    ["missing timestamp", body({ items: [{ ...EVENT, at: undefined }] })],
    ["page larger than its limit", body({ items: [EVENT, EVENT], limit: 1 })],
    ["items not a list", body({ items: "x" })],
    ["missing counts", body({ last_24h: undefined })],
    ["negative count", body({ last_24h: { chat_refused: -1 } })],
    ["string count", body({ last_24h: { chat_refused: "3" } })],
  ])("rejects %s", (_name, bad) => {
    expect(() => parseSecurityPage(bad)).toThrow();
  });
});

describe("fetchSecurityEvents", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks with the bearer token and the paging", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(Response.json(body())));
    vi.stubGlobal("fetch", fetchMock);

    await fetchSecurityEvents("tok.en.x", { limit: 10, offset: 20 });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toBe("https://api.example/admin/security?limit=10&offset=20");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok.en.x");
  });
});
