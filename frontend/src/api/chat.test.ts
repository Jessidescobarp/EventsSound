import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildHistory,
  CHAT_TIMEOUT_MS,
  checkDraft,
  classifyChatError,
  MAX_BODY_BYTES,
  MAX_MESSAGE_CHARS,
  MAX_TOTAL_CHARS,
  parseChatResponse,
  sendChat,
  type ChatTurn,
} from "./chat";
import { ApiError } from "./client";

const line = (over: Record<string, unknown>) => ({
  kind: "item", code: "a", label: "Parlante", quantity: 2, periods: 1,
  unit_amount: 1000, rate_bps: null, basis: null, amount: 2000, ...over,
});
const quoteBody = (over: Record<string, unknown> = {}) => ({
  version: 1, rules_version: "synthetic-v1", currency: "COP", rental_days: 1,
  lines: [line({}), line({ kind: "rounding", code: "rounding", label: null, unit_amount: null, amount: 100, quantity: 1 })],
  subtotal: 2000, total: 2100, ...over,
});
const response = (over: Record<string, unknown> = {}) => ({
  request_id: "r1", status: "quote", reply: "Listo", quote: quoteBody(), event_request: null,
  availability: { is_available: true, shortages: [] }, missing_fields: [], reply_source: "llm", ...over,
});

describe("parseChatResponse", () => {
  it.each([
    ["quote", response()],
    ["multi-line reply", response({ reply: "Linea 1\nLinea 2\t3" })],
    ["clarification", response({ status: "clarification", quote: null, availability: null, missing_fields: ["guest_count"], reply_source: "static" })],
    ["discount and signed rounding", response({ quote: quoteBody({
      lines: [line({ amount: 2000 }), line({ kind: "package_discount", code: "a", unit_amount: null, amount: -200 }), line({ kind: "rounding", code: "rounding", label: null, unit_amount: null, amount: -100 })],
      subtotal: 1800, total: 1700 }) })],
  ])("accepts a valid %s", (_name, body) => {
    expect(parseChatResponse(body).request_id).toBe("r1");
  });

  it.each([
    ["not an object", "hola"],
    ["missing reply", response({ reply: undefined })],
    ["unknown reply_source", response({ reply_source: "oracle" })],
    ["unknown status", response({ status: "done" })],
    ["quote status without quote", response({ quote: null })],
    ["quote with a clarification status", response({ status: "clarification" })],
    ["oversized reply", response({ reply: "x".repeat(6001) })],
    ["line break inside a label", response({ quote: quoteBody({ lines: [line({ label: "a\nb", amount: 2000 })], subtotal: 2000, total: 2000 }) })],
    ["negative surcharge", response({ quote: quoteBody({ lines: [line({}), line({ kind: "night", code: "night", label: null, unit_amount: null, amount: -100 })], subtotal: 1900, total: 1900 }) })],
    ["unknown line kind", response({ quote: quoteBody({ lines: [line({ kind: "constructor" })], subtotal: 2000, total: 2000 }) })],
    ["more than 250 lines", response({ quote: quoteBody({ lines: Array.from({ length: 251 }, (_, i) => line({ code: `c${i}`, amount: 0 })), subtotal: 0, total: 0 }) })],
    ["total as string", response({ quote: quoteBody({ total: "2100" }) })],
    ["float pesos", response({ quote: quoteBody({ total: 2100.5 }) })],
    ["huge number", response({ quote: quoteBody({ total: 1e300 }) })],
    ["negative total", response({ quote: quoteBody({ total: -1 }) })],
    ["negative item amount", response({ quote: quoteBody({ lines: [line({ amount: -2000 })], subtotal: -2000, total: -2000 }) })],
    ["wrong currency", response({ quote: quoteBody({ currency: "USD" }) })],
    ["duplicate line", response({ quote: quoteBody({ lines: [line({}), line({})], subtotal: 4000, total: 4000 }) })],
    ["lines that do not add up", response({ quote: quoteBody({ total: 9999 }) })],
    ["rounding not last", response({ quote: quoteBody({ lines: [line({ kind: "rounding", code: "rounding", label: null, amount: 100 }), line({})] }) })],
    ["shortage with float", response({ availability: { is_available: false, shortages: [{ item_code: "a", requested: 1.5, available: 0 }] } })],
    ["missing_fields not strings", response({ missing_fields: [1] })],
    ["options not an array", response({ options: "Paquete DJ" })],
    ["option not a string", response({ options: [1] })],
    ["empty option", response({ options: [" "] })],
    ["overlong option", response({ options: ["x".repeat(121)] })],
    ["option with a line break", response({ options: ["a\nb"] })],
    ["too many options", response({ options: Array.from({ length: 13 }, (_, i) => `o${i}`) })],
  ])("rejects %s", (_name, body) => {
    expect(() => parseChatResponse(body)).toThrow();
  });

  it.each([
    ["absent", response(), []],
    ["empty", response({ options: [] }), []],
    ["present", response({ options: ["Paquete DJ", "Ver todo el catalogo"] }), ["Paquete DJ", "Ver todo el catalogo"]],
  ])("reads options when %s", (_name, body, expected) => {
    expect(parseChatResponse(body).options).toEqual(expected);
  });

  it("accepts 250 lines and 250 shortages", () => {
    const lines = Array.from({ length: 250 }, (_, i) => line({ code: `c${i}`, amount: 0 }));
    const shortages = Array.from({ length: 250 }, (_, i) => ({ item_code: `c${i}`, requested: 1, available: 0 }));
    const parsed = parseChatResponse(response({ quote: quoteBody({ lines, subtotal: 0, total: 0 }), availability: { is_available: false, shortages } }));
    expect(parsed.quote?.lines).toHaveLength(250);
  });

  it("keeps the reply but turns C1 controls and bidi marks into spaces", () => {
    expect(parseChatResponse(response({ reply: "a\u0085b‮c\nd" })).reply).toBe("a b c\nd");
  });
});

describe("request building", () => {
  const user = (content: string): ChatTurn => ({ role: "user", content });
  const assistant = (content: string): ChatTurn => ({ role: "assistant", content });
  const chars = (turns: ChatTurn[]) => turns.reduce((n, t) => n + Array.from(t.content).length, 0);
  const bytes = (turns: ChatTurn[]) => new TextEncoder().encode(JSON.stringify({ messages: turns })).length;

  it.each([
    ["keeps the last 16 turns", Array.from({ length: 20 }, (_, i) => user(`m${i}`)), 16],
    ["clips each message to the limit", [user("x".repeat(MAX_MESSAGE_CHARS + 50))], 1],
    ["drops the oldest to fit the total characters", Array.from({ length: 6 }, () => user("y".repeat(900))), 4],
    ["keeps exactly 4000 characters", [...Array.from({ length: 4 }, () => user("y".repeat(800))), user("y".repeat(800))], 5],
    ["drops one turn at 4001 characters", [...Array.from({ length: 4 }, () => user("y".repeat(800))), user("y".repeat(801))], 4],
  ])("%s", (_name, turns, expectedLength) => {
    const history = buildHistory(turns);
    expect(history).toHaveLength(expectedLength);
    expect(chars(history)).toBeLessThanOrEqual(MAX_TOTAL_CHARS);
    expect(bytes(history)).toBeLessThanOrEqual(MAX_BODY_BYTES);
    expect(history.at(-1)?.content).toBe(turns.at(-1)?.content.slice(0, MAX_MESSAGE_CHARS));
  });

  it("keeps roles and counts emoji as one character each", () => {
    expect(buildHistory([user("hola"), assistant("ok"), user("😀".repeat(MAX_MESSAGE_CHARS))]).map((t) => t.role)).toEqual(["user", "assistant", "user"]);
  });

  it.each([
    ["", "empty"],
    ["   \n ", "empty"],
    ["x".repeat(MAX_MESSAGE_CHARS), null],
    ["😀".repeat(MAX_MESSAGE_CHARS), null],
    ["x".repeat(MAX_MESSAGE_CHARS + 1), "too_long"],
    ["​‍⁠﻿ \u0001", "empty"], // only zero-width and control characters
    ["<>", "empty"],
    ["…".repeat(400), "too_long"], // NFKC turns each ellipsis into 3 characters: 1200
    ["…".repeat(333) + "x" + " ".repeat(500), null], // 1000 characters once cleaned
    ["a \n\t  b", null],
  ])("checkDraft(%#) is %s", (raw, expected) => {
    expect(checkDraft(raw)).toBe(expected);
  });

  it("sends the cleaned text of every turn and drops turns that clean to nothing", () => {
    const history = buildHistory([user("​"), assistant("a\u0000 <b>  c"), user("ﬁ")]);
    expect(history).toEqual([assistant("a b c"), user("fi")]);
  });

  describe("body size", () => {
    const empty = new TextEncoder().encode(JSON.stringify({ messages: [{ role: "user", content: "" }] })).length;
    it.each([
      [MAX_BODY_BYTES, 1, 0],
      [MAX_BODY_BYTES + 1, 0, 1],
    ])("a body of %i bytes calls fetch %i time(s) and refuses %i", async (size, calls, refused) => {
      const fetchMock = vi.fn(() => Promise.reject(new TypeError("offline")));
      vi.stubGlobal("fetch", fetchMock);
      vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
      const outcome = await sendChat([user("x".repeat(size - empty))]).catch((e: ApiError) => e);
      expect(fetchMock).toHaveBeenCalledTimes(calls);
      expect(outcome instanceof ApiError && outcome.status === 413 ? 1 : 0).toBe(refused);
    });
  });

  it("waits longer than the 40 s backend deadline", () => {
    expect(CHAT_TIMEOUT_MS).toBeGreaterThan(40_000);
  });
});

describe("classifyChatError", () => {
  afterEach(() => vi.unstubAllGlobals());
  const err = (code: ConstructorParameters<typeof ApiError>[0], status?: number, detail?: string) =>
    new ApiError(code, "x", status, { detail });

  it.each([
    [err("server", 503, "chat_disabled"), "disabled"],
    [err("server", 503, "daily_budget_exhausted"), "budget"],
    [err("server", 503, "llm_unavailable"), "transient"],
    [err("server", 500, "internal_error"), "transient"],
    [err("http", 429, "rate_limited"), "rate_limited"],
    [err("http", 413, "payload_too_large"), "invalid"],
    [err("http", 422, "invalid_request"), "invalid"],
    [err("network"), "transient"],
    [err("timeout"), "transient"],
    [err("invalid_response"), "unexpected"],
    [err("too_large"), "unexpected"],
    [err("aborted"), "aborted"],
    [new Error("boom"), "unexpected"],
  ])("maps %# to %s", (error, expected) => {
    expect(classifyChatError(error)).toBe(expected);
  });
});
