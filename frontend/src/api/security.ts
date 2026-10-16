import { apiFetch } from "./client";
import { int, obj, str } from "./parse";
import { parsePage, query, type Page, type Paging } from "./records";

/** Contract of GET /admin/security (backend security events). The client key is a hash, never an IP. */
export const SECURITY_KINDS = ["chat_refused", "login_failed"] as const;
export type SecurityKind = (typeof SECURITY_KINDS)[number];

export interface SecurityEvent {
  id: number;
  at: string;
  kind: SecurityKind;
  client: string;
}

export interface SecurityPage extends Page<SecurityEvent> {
  last_24h: Record<SecurityKind, number>;
}

const MAX_COUNT = 1_000_000_000;

function parseEvent(value: unknown): SecurityEvent {
  const o = obj(value);
  const kind = str(o, "kind", 32);
  if (!(SECURITY_KINDS as readonly string[]).includes(kind)) throw new Error("kind: unknown");
  const client = str(o, "client", 16);
  if (!/^[0-9a-f]{16}$/.test(client)) throw new Error("client: invalid key");
  return { id: int(o, "id", 1, MAX_COUNT), at: str(o, "at", 40), kind: kind as SecurityKind, client };
}

/** A kind the server leaves out has no events in the window: it counts as zero. */
function parseCounts(value: unknown): SecurityPage["last_24h"] {
  const o = obj(value);
  const read = (kind: SecurityKind) => (o[kind] === undefined ? 0 : int(o, kind, 0, MAX_COUNT));
  return { chat_refused: read("chat_refused"), login_failed: read("login_failed") };
}

export function parseSecurityPage(json: unknown): SecurityPage {
  return { ...parsePage(json, parseEvent), last_24h: parseCounts(obj(json).last_24h) };
}

export function fetchSecurityEvents(token: string, paging: Paging, signal?: AbortSignal) {
  return apiFetch(`/admin/security${query(paging)}`, { parse: parseSecurityPage, token, signal });
}
