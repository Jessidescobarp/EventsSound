import { ApiError, apiFetch } from "./client";
import { int, list, nullable, obj, str } from "./parse";

/**
 * Contract of POST /quote/chat (openspec quote-agent / chat-endpoint). The server keeps no
 * conversation: every request carries the bounded history. Limits mirror the backend
 * (schemas.py, guards.py); the server stays the authority, these only avoid useless calls.
 */
export const MAX_MESSAGES = 16; // keep equal to MAX_MESSAGES in backend schemas.py (contract test)
export const MAX_MESSAGE_CHARS = 1000;
export const MAX_TOTAL_CHARS = 4000;
export const MAX_BODY_BYTES = 16 * 1024;
/**
 * Chat answers wait for an LLM. Keep this ABOVE the backend deadline (40 s): aborting first
 * would drop an answer whose tokens are already spent, and a retry would pay twice.
 */
export const CHAT_TIMEOUT_MS = 60_000;

export type ChatRole = "user" | "assistant";
export interface ChatTurn {
  role: ChatRole;
  content: string;
}

// ---- request building ----

/** Characters as the backend counts them (Python len = code points, not UTF-16 units). */
export function countChars(value: string): number {
  return Array.from(value).length;
}

function clip(value: string, max: number): string {
  return countChars(value) <= max ? value : Array.from(value).slice(0, max).join("");
}

const encoder = new TextEncoder();
const bodyBytes = (turns: ChatTurn[]) => encoder.encode(JSON.stringify({ messages: turns })).length;

/**
 * Last MAX_MESSAGES turns, each clipped to the per-message limit, dropping the oldest until
 * the total characters and the UTF-8 body fit. The newest turn is always kept.
 */
export function buildHistory(turns: ChatTurn[]): ChatTurn[] {
  let history = turns
    .slice(-MAX_MESSAGES)
    .map((t) => ({ role: t.role, content: clip(cleanText(t.content), MAX_MESSAGE_CHARS) }))
    .filter((t) => t.content.length > 0); // the server rejects a turn that is empty once cleaned
  const total = (h: ChatTurn[]) => h.reduce((sum, t) => sum + countChars(t.content), 0);
  while (history.length > 1 && (total(history) > MAX_TOTAL_CHARS || bodyBytes(history) > MAX_BODY_BYTES)) {
    history = history.slice(1);
  }
  return history;
}

export type DraftProblem = "empty" | "too_long";

// Mirrors _clean in backend application/chat_input.py: controls, zero-width and bidi marks
// become spaces, angle brackets go, whitespace collapses. Limits apply AFTER this.
// eslint-disable-next-line no-control-regex
const INPUT_NOISE = /[\x00-\x1f\x7f\x80-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\u180e\ufeff]/g;

/** The text the server will see for a message. */
export function cleanText(raw: string): string {
  return raw.normalize("NFKC").replace(INPUT_NOISE, " ").replace(/[<>]/g, "").replace(/\s+/g, " ").trim();
}

/** Checks what the user typed, as the server will see it, before it is sent. */
export function checkDraft(raw: string): DraftProblem | null {
  const cleaned = cleanText(raw);
  if (cleaned.length === 0) return "empty";
  const tooBig = countChars(cleaned) > MAX_MESSAGE_CHARS || bodyBytes([{ role: "user", content: cleaned }]) > MAX_BODY_BYTES;
  return tooBig ? "too_long" : null;
}

// ---- response types ----

export type ReplySource = "llm" | "template" | "static";
export type ChatStatus = "clarification" | "quote" | "refused";

export interface QuoteLine {
  kind: string;
  code: string;
  label: string | null;
  quantity: number;
  periods: number;
  unit_amount: number | null;
  rate_bps: number | null;
  basis: number | null;
  amount: number;
}

export interface Quote {
  version: 1;
  currency: "COP";
  rental_days: number;
  lines: QuoteLine[];
  subtotal: number;
  total: number;
}

export interface Shortage {
  item_code: string;
  requested: number;
  available: number;
}

export interface Availability {
  is_available: boolean;
  shortages: Shortage[];
}

export interface ChatResponse {
  request_id: string;
  status: ChatStatus;
  reply: string;
  quote: Quote | null;
  availability: Availability | null;
  missing_fields: string[];
  reply_source: ReplySource;
  /** Short suggested answers; each is sent back verbatim as the next user message. */
  options: string[];
}

// ---- runtime guards: the JSON is untrusted ----

const MAX_REPLY_CHARS = 6000;
const MAX_LINES = 250;
const MAX_LIST = 250;
const MAX_OPTIONS = 12;
/** Wire value of the backend's VIEW_ALL_OPTION (messages_es.py): the UI links to the catalog instead of sending it. */
export const VIEW_ALL_OPTION = "Ver todo el catalogo";
const MAX_PESOS = 1_000_000_000_000;
const STATUSES: readonly string[] = ["clarification", "quote", "refused"];
const SOURCES: readonly string[] = ["llm", "template", "static"];
/** Only these lines may be negative: discounts and the signed rounding adjustment. */
const SIGNED_KINDS: readonly string[] = ["package_discount", "rounding"];

/** The closed set of backend LineKind values (domain/pricing.py). */
const KINDS: readonly string[] = [
  "item", "package", "package_discount", "guest_size", "weekend_holiday", "night", "distance", "rounding",
];

function parseLine(value: unknown): QuoteLine {
  const o = obj(value);
  const kind = str(o, "kind", 32);
  if (!KINDS.includes(kind)) throw new Error("kind: unknown line kind");
  const optional = (key: string, min: number) => nullable(o[key], () => int(o, key, min, MAX_PESOS));
  const min = SIGNED_KINDS.includes(kind) ? -MAX_PESOS : 0;
  return {
    kind,
    code: str(o, "code", 64),
    label: nullable(o.label, () => str(o, "label")),
    quantity: int(o, "quantity", 0, 100_000),
    periods: int(o, "periods", 0, 1_000),
    unit_amount: optional("unit_amount", 0),
    rate_bps: nullable(o.rate_bps, () => int(o, "rate_bps", 0, 100_000)),
    basis: optional("basis", 0),
    amount: int(o, "amount", min, MAX_PESOS),
  };
}

/** The pricing engine guarantees these identities; a payload that breaks them is not trusted. */
export function parseQuote(value: unknown): Quote {
  const o = obj(value);
  if (int(o, "version", 1, 1) !== 1 || o.currency !== "COP") throw new Error("unsupported quote");
  const lines = list(o.lines, MAX_LINES, parseLine);
  const subtotal = int(o, "subtotal", 0, MAX_PESOS);
  const total = int(o, "total", 0, MAX_PESOS);
  const keys = new Set(lines.map((l) => `${l.kind}:${l.code}`));
  const rounding = lines.findIndex((l) => l.kind === "rounding");
  const raw = lines.filter((l) => l.kind !== "rounding").reduce((sum, l) => sum + l.amount, 0);
  const all = lines.reduce((sum, l) => sum + l.amount, 0);
  const roundingOk = rounding === -1 || rounding === lines.length - 1;
  if (lines.length === 0 || keys.size !== lines.length || !roundingOk || raw !== subtotal || all !== total) {
    throw new Error("quote lines do not reconcile");
  }
  return { version: 1, currency: "COP", rental_days: int(o, "rental_days", 1, 365), lines, subtotal, total };
}

function parseAvailability(value: unknown): Availability {
  const o = obj(value);
  if (typeof o.is_available !== "boolean") throw new Error("is_available: boolean expected");
  const shortages = list(o.shortages, MAX_LIST, (v) => {
    const s = obj(v);
    return { item_code: str(s, "item_code", 64), requested: int(s, "requested", 0, 100_000), available: int(s, "available", 0, 100_000) };
  });
  return { is_available: o.is_available, shortages };
}

export function parseChatResponse(json: unknown): ChatResponse {
  const o = obj(json);
  const status = str(o, "status", 16);
  const source = str(o, "reply_source", 16);
  if (!STATUSES.includes(status) || !SOURCES.includes(source)) throw new Error("unknown enum value");
  const quote = nullable(o.quote, parseQuote);
  if ((status === "quote") !== (quote !== null)) throw new Error("quote presence must follow status");
  return {
    request_id: str(o, "request_id", 64),
    status: status as ChatStatus,
    reply: str(o, "reply", MAX_REPLY_CHARS, true),
    quote,
    availability: nullable(o.availability, parseAvailability),
    missing_fields: list(o.missing_fields, MAX_LIST, (v) => str({ code: v }, "code", 64)),
    reply_source: source as ReplySource,
    options: o.options === undefined ? [] : list(o.options, MAX_OPTIONS, (v) => str({ option: v }, "option")),
  };
}

// ---- welcome message (GET /quote/config, public) ----

export const MAX_WELCOME_CHARS = 400;
const MAX_WELCOME_LINE_BREAKS = 6;

/** Strict: an object with a 1..400 char string and no line-break flood, else it is a failure. */
export function parseWelcome(json: unknown): string {
  const text = str(obj(json), "welcome_message", MAX_WELCOME_CHARS, true).trim();
  if (text.split("\n").length - 1 > MAX_WELCOME_LINE_BREAKS) throw new Error("welcome_message: too many lines");
  return text;
}

/** Throws ApiError. The caller falls back to the built-in greeting on any failure. */
export function fetchWelcome(signal?: AbortSignal): Promise<string> {
  return apiFetch("/quote/config", { parse: parseWelcome, signal });
}

// ---- transport and error classes ----

/** Throws ApiError. A body over the byte limit is refused here, before the network. */
export function sendChat(history: ChatTurn[], signal?: AbortSignal, token?: string): Promise<ChatResponse> {
  if (history.length === 0 || bodyBytes(history) > MAX_BODY_BYTES) {
    return Promise.reject(new ApiError("http", "Request too large.", 413));
  }
  return apiFetch("/quote/chat", {
    method: "POST",
    jsonBody: { messages: history },
    parse: parseChatResponse,
    signal,
    timeoutMs: CHAT_TIMEOUT_MS,
    token,
  });
}

/**
 * disabled: kill switch, no retry loop. rate_limited: wait. budget: out of daily budget.
 * invalid: 413/422, the message must change. transient: network, timeout or 5xx, retry makes sense.
 * unexpected: the answer was not our contract. aborted: the caller left; show nothing.
 */
export type ChatFailure = "disabled" | "rate_limited" | "budget" | "invalid" | "transient" | "unexpected" | "aborted";

export function classifyChatError(error: unknown): ChatFailure {
  if (!(error instanceof ApiError)) return "unexpected";
  const { code, status, detail } = error;
  if (code === "aborted") return "aborted";
  if (status === 503 && detail === "chat_disabled") return "disabled";
  if (status === 503 && detail === "daily_budget_exhausted") return "budget";
  if (status === 429) return "rate_limited";
  if (status === 413 || status === 422) return "invalid";
  if (code === "network" || code === "timeout" || code === "server") return "transient";
  return "unexpected";
}
