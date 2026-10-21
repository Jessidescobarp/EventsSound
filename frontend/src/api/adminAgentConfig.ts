import { ApiError, apiFetch } from "./client";
import { bool, int, list, nullable, obj, str, type Obj } from "./parse";

/** Contract of /admin/agent-config (backend routes/admin_agent_config.py). The server stays the authority. */
export const TONES = ["formal", "cercano", "neutral"] as const;
export const OFF_TOPIC_POLICIES = ["strict", "normal"] as const;
export const TEXT_FIELDS = ["refusal_message", "closing_message", "welcome_message"] as const;
export const MAX_TEXT_CHARS = 400;
export const MAX_NOTE_CHARS = 200;
export const MICRO_PER_USD = 1_000_000;

export interface AgentConfig {
  tone: (typeof TONES)[number];
  off_topic_policy: (typeof OFF_TOPIC_POLICIES)[number];
  refusal_message: string;
  closing_message: string;
  welcome_message: string;
  llm_model: string;
  daily_token_cap: number;
  daily_cost_cap_micro_usd: number;
  chat_rate_limit_per_minute: number;
}
export type ConfigField = keyof AgentConfig;

export interface ModelInUse {
  provider: string;
  model: string;
  status: "active" | "disabled" | "replay";
  input_price_per_mtok: number;
  output_price_per_mtok: number;
  cost_cap_applies: boolean;
}

export interface AgentConfigView {
  version: number;
  config: AgentConfig;
  ceilings: { max_daily_tokens: number; max_daily_cost_micro_usd: number; max_rate_limit_per_minute: number };
  allowed_models: string[];
  model_in_use: ModelInUse;
  defaults_out_of_bounds: string[];
  updated_at: string | null;
}

export type DiffValue = string | number | boolean | null;
export type Diff = Record<string, [DiffValue, DiffValue]>;
export type Severity = "info" | "warning" | "danger";

export interface Preview {
  action: "save" | "rollback";
  base_version: number;
  diff: Diff;
  warnings: { code: string; severity: Severity; message_es: string }[];
  requires_password: boolean;
  max_daily_cost_estimate_micro_usd: number | null;
  confirmation_token: string;
  expires_at: string;
}

export interface HistoryItem {
  version: number;
  created_at: string;
  created_by: string | null;
  note: string | null;
  action: "save" | "rollback";
  diff: Diff;
}

/** Exactly one of `changes` / `rollback_to_version`, as the backend demands. */
export type ConfigChange =
  | { changes: Partial<AgentConfig>; base_version: number }
  | { rollback_to_version: number; base_version: number };

export interface Confirmation {
  confirmation_token: string;
  typed_confirmation: string;
  password?: string;
  note?: string;
}

// ---- strict parsers: reject unexpected shapes, tolerate extra fields ----

const MAX_INT = 1_000_000_000_000;
const oneOf = <T extends string>(o: Obj, key: string, allowed: readonly T[]): T => {
  const v = str(o, key, 32);
  if (!(allowed as readonly string[]).includes(v)) throw new Error(`${key}: unknown value`);
  return v as T;
};

function parseConfig(value: unknown): AgentConfig {
  const o = obj(value);
  return {
    tone: oneOf(o, "tone", TONES),
    off_topic_policy: oneOf(o, "off_topic_policy", OFF_TOPIC_POLICIES),
    refusal_message: str(o, "refusal_message", MAX_TEXT_CHARS, true),
    closing_message: str(o, "closing_message", MAX_TEXT_CHARS, true),
    welcome_message: str(o, "welcome_message", MAX_TEXT_CHARS, true),
    llm_model: str(o, "llm_model", 120),
    daily_token_cap: int(o, "daily_token_cap", 0, MAX_INT),
    daily_cost_cap_micro_usd: int(o, "daily_cost_cap_micro_usd", 0, MAX_INT),
    chat_rate_limit_per_minute: int(o, "chat_rate_limit_per_minute", 0, MAX_INT),
  };
}

function parseModel(value: unknown): ModelInUse {
  const o = obj(value);
  return {
    provider: str(o, "provider", 40),
    model: str(o, "model", 120),
    status: oneOf(o, "status", ["active", "disabled", "replay"] as const),
    input_price_per_mtok: int(o, "input_price_per_mtok", 0, MAX_INT),
    output_price_per_mtok: int(o, "output_price_per_mtok", 0, MAX_INT),
    cost_cap_applies: bool(o, "cost_cap_applies"),
  };
}

const item = (v: unknown) => str({ v }, "v", 120);

export function parseConfigView(json: unknown): AgentConfigView {
  const o = obj(json);
  const ceilings = obj(o.ceilings);
  return {
    version: int(o, "version", 0, MAX_INT),
    config: parseConfig(o.config),
    ceilings: {
      max_daily_tokens: int(ceilings, "max_daily_tokens", 1, MAX_INT),
      max_daily_cost_micro_usd: int(ceilings, "max_daily_cost_micro_usd", 1, MAX_INT),
      max_rate_limit_per_minute: int(ceilings, "max_rate_limit_per_minute", 1, MAX_INT),
    },
    allowed_models: list(o.allowed_models, 50, item),
    model_in_use: parseModel(o.model_in_use),
    defaults_out_of_bounds: list(o.defaults_out_of_bounds, 12, item),
    updated_at: nullable(o.updated_at, (v) => str({ v }, "v", 40)),
  };
}

function diffValue(v: unknown): DiffValue {
  if (v === null || typeof v === "boolean") return v;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.length <= 1000) return v;
  throw new Error("diff: unexpected value");
}

function parseDiff(value: unknown): Diff {
  const o = obj(value);
  const keys = Object.keys(o);
  if (keys.length > 12) throw new Error("diff: too many fields");
  return Object.fromEntries(
    keys.map((key) => {
      if (!/^[a-z_]{1,64}$/.test(key)) throw new Error("diff: invalid field");
      const pair = list(o[key], 2, diffValue);
      if (pair.length !== 2) throw new Error("diff: pair expected");
      return [key, [pair[0], pair[1]] as [DiffValue, DiffValue]];
    }),
  );
}

export function parsePreview(json: unknown): Preview {
  const o = obj(json);
  return {
    action: oneOf(o, "action", ["save", "rollback"] as const),
    base_version: int(o, "base_version", 0, MAX_INT),
    diff: parseDiff(o.diff),
    warnings: list(o.warnings, 20, (v) => {
      const w = obj(v);
      return { code: str(w, "code", 48), severity: oneOf(w, "severity", ["info", "warning", "danger"] as const), message_es: str(w, "message_es", 300) };
    }),
    requires_password: bool(o, "requires_password"),
    max_daily_cost_estimate_micro_usd: nullable(o.max_daily_cost_estimate_micro_usd, (v) =>
      int({ v }, "v", 0, MAX_INT),
    ),
    confirmation_token: str(o, "confirmation_token", 2000),
    expires_at: str(o, "expires_at", 40),
  };
}

export function parseApplied(json: unknown): { version: number; config: AgentConfig; applied_at: string } {
  const o = obj(json);
  return { version: int(o, "version", 1, MAX_INT), config: parseConfig(o.config), applied_at: str(o, "applied_at", 40) };
}

export function parseHistory(json: unknown): HistoryItem[] {
  return list(json, 100, (v) => {
    const o = obj(v);
    return {
      version: int(o, "version", 1, MAX_INT),
      created_at: str(o, "created_at", 40),
      created_by: nullable(o.created_by, (x) => str({ x }, "x", 64)),
      note: nullable(o.note, (x) => str({ x }, "x", MAX_NOTE_CHARS)),
      action: oneOf(o, "action", ["save", "rollback"] as const),
      diff: parseDiff(o.diff),
    };
  });
}

// ---- requests ----

const BASE = "/admin/agent-config";

export const fetchAgentConfig = (token: string, signal?: AbortSignal) =>
  apiFetch(BASE, { parse: parseConfigView, token, signal });

export const previewAgentConfig = (change: ConfigChange, token: string, signal?: AbortSignal) =>
  apiFetch(`${BASE}/preview`, { method: "POST", jsonBody: change, parse: parsePreview, token, signal });

export const applyAgentConfig = (change: ConfigChange, confirmation: Confirmation, token: string, signal?: AbortSignal) =>
  apiFetch(`${BASE}/apply`, { method: "PUT", jsonBody: { ...change, ...confirmation }, parse: parseApplied, token, signal });

export const fetchAgentHistory = (token: string, signal?: AbortSignal) =>
  apiFetch(`${BASE}/history?limit=20`, { parse: parseHistory, token, signal });

// ---- error mapping ----

export type ConfigFailure =
  | "unauthenticated"
  | "forbidden"
  | "reauth_failed" // wrong password or account no longer allowed
  | "token_stale" // used, expired, mismatched or invalid: preview again
  | "version_conflict"
  | "invalid_config"
  | "no_changes"
  | "unknown_version"
  | "typed_confirmation"
  | "password_required"
  | "rate_limited"
  | "confirmation_unavailable"
  | "unavailable"
  | "transient"
  | "unexpected"
  | "aborted";

const BY_DETAIL: Record<string, ConfigFailure> = {
  reauth_failed: "reauth_failed",
  token_invalid: "token_stale",
  token_expired: "token_stale",
  token_used: "token_stale",
  token_mismatch: "token_stale",
  version_conflict: "version_conflict",
  invalid_config: "invalid_config",
  invalid_request: "invalid_config",
  no_changes: "no_changes",
  unknown_version: "unknown_version",
  typed_confirmation_invalid: "typed_confirmation",
  password_required: "password_required",
  rate_limited: "rate_limited",
  confirmation_unavailable: "confirmation_unavailable",
  storage_unavailable: "unavailable",
  auth_unavailable: "unavailable",
};

export function classifyConfigError(error: unknown): ConfigFailure {
  if (!(error instanceof ApiError)) return "unexpected";
  const { code, status, detail } = error;
  if (code === "aborted") return "aborted";
  if (status === 401) return "unauthenticated";
  if (detail && Object.hasOwn(BY_DETAIL, detail)) return BY_DETAIL[detail]!;
  if (status === 403) return "forbidden";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  if (code === "network" || code === "timeout" || code === "server") return "transient";
  return "unexpected";
}
