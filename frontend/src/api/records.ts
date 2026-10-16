import { ApiError, apiFetch } from "./client";
import { parseQuote, type Quote } from "./chat";
import { bool, int, list, nullable, obj, str } from "./parse";

/** Contract of GET /me/quotes, /admin/quotes and /admin/bookings (backend routes/records.py). */
export const PAGE_SIZE = 10;
const MAX_ROWS = 100;
const MAX_OFFSET = 100_000;
const MAX_PESOS = 1_000_000_000_000;

export interface Paging {
  limit: number;
  offset: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface QuoteRecord {
  id: string;
  created_at: string;
  registered: boolean;
  owner_email: string | null;
  event_type: string;
  event_start: string;
  event_end: string;
  guest_count: number;
  total_cop: number;
  available: boolean | null;
  /** Null when the stored breakdown no longer matches the current shape: the row still lists. */
  quote: Quote | null;
}

export interface BookingRecord {
  booking_code: string;
  item_code: string;
  quantity: number;
  starts_at: string;
  ends_at: string;
  status: string;
  created_at: string;
}

function readQuote(value: unknown): Quote | null {
  try {
    return parseQuote(value);
  } catch {
    return null;
  }
}

function parseQuoteRecord(value: unknown): QuoteRecord {
  const o = obj(value);
  return {
    id: str(o, "id", 64),
    created_at: str(o, "created_at", 40),
    registered: bool(o, "registered"),
    owner_email: nullable(o.owner_email, () => str(o, "owner_email", 254)),
    event_type: str(o, "event_type", 32),
    event_start: str(o, "event_start", 40),
    event_end: str(o, "event_end", 40),
    guest_count: int(o, "guest_count", 1, 1_000_000),
    total_cop: int(o, "total_cop", 0, MAX_PESOS),
    available: nullable(o.available, () => bool(o, "available")),
    quote: readQuote(o.quote),
  };
}

function parseBookingRecord(value: unknown): BookingRecord {
  const o = obj(value);
  return {
    booking_code: str(o, "booking_code", 64),
    item_code: str(o, "item_code", 64),
    quantity: int(o, "quantity", 1, 100_000),
    starts_at: str(o, "starts_at", 40),
    ends_at: str(o, "ends_at", 40),
    status: str(o, "status", 16),
    created_at: str(o, "created_at", 40),
  };
}

function parsePage<T>(json: unknown, read: (value: unknown) => T): Page<T> {
  const o = obj(json);
  const items = list(o.items, MAX_ROWS, read);
  const limit = int(o, "limit", 1, MAX_ROWS);
  const total = int(o, "total", 0, 1_000_000_000);
  if (items.length > limit) throw new Error("page larger than its limit");
  return { items, total, limit, offset: int(o, "offset", 0, MAX_OFFSET) };
}

const query = ({ limit, offset }: Paging) => `?limit=${limit}&offset=${offset}`;

export const parseQuotePage = (json: unknown) => parsePage(json, parseQuoteRecord);
export const parseBookingPage = (json: unknown) => parsePage(json, parseBookingRecord);

export function fetchMyQuotes(token: string, paging: Paging, signal?: AbortSignal) {
  return apiFetch(`/me/quotes${query(paging)}`, { parse: parseQuotePage, token, signal });
}

export function fetchAdminQuotes(token: string, paging: Paging, signal?: AbortSignal) {
  return apiFetch(`/admin/quotes${query(paging)}`, { parse: parseQuotePage, token, signal });
}

export function fetchAdminBookings(token: string, paging: Paging, signal?: AbortSignal) {
  return apiFetch(`/admin/bookings${query(paging)}`, { parse: parseBookingPage, token, signal });
}

/** unauthenticated: the token is missing, expired or rejected (sign in again). */
export type RecordsFailure =
  | "unauthenticated"
  | "forbidden"
  | "unavailable"
  | "transient"
  | "unexpected"
  | "aborted";

export function classifyRecordsError(error: unknown): RecordsFailure {
  if (!(error instanceof ApiError)) return "unexpected";
  const { code, status } = error;
  if (code === "aborted") return "aborted";
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 503 && code !== "network") return "unavailable";
  if (code === "network" || code === "timeout" || code === "server") return "transient";
  return "unexpected";
}
