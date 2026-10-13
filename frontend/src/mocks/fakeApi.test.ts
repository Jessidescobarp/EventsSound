import { beforeEach, describe, expect, it, vi } from "vitest";
import { parseItems, parsePackages } from "../api/catalog";
import { parseChatResponse } from "../api/chat";
import { createFakeFetch, installMocks, MOCK_ITEMS, MOCK_PACKAGES } from "./fakeApi";

describe("fake API", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  });

  const fake = createFakeFetch({ latencyMs: 0 });

  it("serves a realistic dataset that satisfies the catalog contract", async () => {
    const items = parseItems(await (await fake("https://api.example/catalog/items")).json());
    const packages = parsePackages(
      await (await fake("https://api.example/catalog/packages")).json(),
    );
    expect(items.length).toBeGreaterThanOrEqual(18);
    expect(packages).toHaveLength(4);
    const codeList = items.map((i) => i.code);
    expect(codeList).toEqual([...codeList].sort());
    const codes = new Set(items.map((i) => i.code));
    for (const p of packages) {
      expect(p.items.length).toBeGreaterThan(0);
      for (const member of p.items) expect(codes.has(member.item_code)).toBe(true);
    }
  });

  it("derives base_price_cop from the members' unit prices", () => {
    const price = new Map(MOCK_ITEMS.map((i) => [i.code, i.unit_price_cop]));
    for (const p of MOCK_PACKAGES) {
      const expected = p.items.reduce(
        (sum, m) => sum + (price.get(m.item_code) ?? 0) * m.quantity,
        0,
      );
      expect(p.base_price_cop).toBe(expected);
    }
  });

  it("answers /health with ok and anything else with 404", async () => {
    expect(await (await fake("https://api.example/health")).json()).toEqual({ status: "ok" });
    expect((await fake("https://api.example/nope")).status).toBe(404);
  });

  it.each([
    ["anything else", "Necesito sonido", 200, "quote"],
    ["pregunta", "una pregunta", 200, "clarification"],
    ["faltante", "hay faltante", 200, "quote"],
    ["limite", "pasaste el limite", 429, "rate_limited"],
    ["apagado", "esta apagado", 503, "chat_disabled"],
  ])("chat scenario %s is deterministic and satisfies the contract", async (_name, text, status, expected) => {
    const post = () =>
      fake("https://api.example/quote/chat", {
        method: "POST",
        body: JSON.stringify({ messages: [{ role: "user", content: text }] }),
      });
    const first = await post();
    expect(first.status).toBe(status);
    const body: unknown = await first.json();
    expect(await (await post()).json()).toEqual(body);
    if (status === 200) {
      const parsed = parseChatResponse(body);
      expect(parsed.status).toBe(expected);
      if (_name === "faltante") expect(parsed.availability?.is_available).toBe(false);
    } else {
      expect((body as { detail: string }).detail).toBe(expected);
    }
  });

  it("installMocks replaces global fetch", () => {
    const original = globalThis.fetch;
    try {
      installMocks();
      expect(globalThis.fetch).not.toBe(original);
    } finally {
      globalThis.fetch = original;
    }
  });
});
