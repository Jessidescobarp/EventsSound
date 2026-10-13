import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildHistory,
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
    ["control characters in reply", response({ reply: "a\u0007b" })],
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
  ])("rejects %s", (_name, body) => {
    expect(() => parseChatResponse(body)).toThrow();
  });
});

describe("request building", () => {
  const user = (content: string): ChatTurn => ({ role: "user", content });
  const assistant = (content: string): ChatTurn => ({ role: "assistant", content });
  const chars = (turns: ChatTurn[]) => turns.reduce((n, t) => n + Array.from(t.content).length, 0);
  const bytes = (turns: ChatTurn[]) => new TextEncoder().encode(JSON.stringify({ messages: turns })).length;

  it.each([
    ["keeps the last 8 turns", Array.from({ length: 12 }, (_, i) => user(`m${i}`)), 8],
    ["clips each message to the limit", [user("x".repeat(MAX_MESSAGE_CHARS + 50))], 1],
    ["drops the oldest to fit the total characters", Array.from({ length: 6 }, () => user("y".repeat(900))), 4],
    // JSON-escaped control characters take 6 bytes each: 4000 characters would be 24 KB.
    ["drops the oldest to fit the UTF-8 body", Array.from({ length: 4 }, () => user("\u0001".repeat(MAX_MESSAGE_CHARS))), 2],
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
  ])("checkDraft(%#) is %s", (raw, expected) => {
    expect(checkDraft(raw)).toBe(expected);
  });

  it("refuses to send a body over 16 KiB without touching the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(sendChat([user("\u0001".repeat(MAX_MESSAGE_CHARS)), user("\u0001".repeat(MAX_MESSAGE_CHARS)), user("\u0001".repeat(MAX_MESSAGE_CHARS))])).rejects.toMatchObject({ status: 413 });
    expect(fetchMock).not.toHaveBeenCalled();
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
