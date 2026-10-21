/**
 * Demonstration-only, stateful fake of /admin/agent-config (preview, apply, history). It mimics the
 * contract closely enough for the UI: versions, one-use confirmation tokens, a password check and
 * the same error codes. Loaded only through fakeApi (mock mode). All data is synthetic.
 */
import type { AgentConfig, ConfigField, Diff, DiffValue } from "../api/adminAgentConfig";

type Status = "active" | "disabled" | "replay";
interface Stored {
  version: number;
  config: AgentConfig;
  note: string | null;
  action: "save" | "rollback";
  diff: Diff;
  at: string;
}

const CEILINGS = { max_daily_tokens: 1_000_000, max_daily_cost_micro_usd: 10_000_000, max_rate_limit_per_minute: 60 };
const MODELS = ["demo/replay", "vendor/model-a", "vendor/model-b", "vendor/model-c:free"];
const isFree = (model: string) => model.endsWith(":free");
const INITIAL: AgentConfig = {
  tone: "cercano",
  off_topic_policy: "strict",
  refusal_message: "Solo puedo ayudarte con cotizaciones de sonido, luces y DJ.",
  closing_message: "Gracias por escribirnos, quedamos atentos.",
  welcome_message: "Hola, soy el asistente de cotizaciones. Cuéntame de tu evento.",
  llm_model: "demo/replay",
  daily_token_cap: 200_000,
  daily_cost_cap_micro_usd: 2_000_000,
  chat_rate_limit_per_minute: 10,
};
const TEXTS: ConfigField[] = ["refusal_message", "closing_message", "welcome_message"];
const MODEL_IN_USE = { provider: "demo", model: "demo/replay", status: "replay" as Status, input_price_per_mtok: 0, output_price_per_mtok: 0, cost_cap_applies: false, free: false };

let history: Stored[] = [];
let used = new Set<string>();
let issued = new Map<string, string>(); // token -> canonical change
let counter = 0;

/** Back to version 0 (tests call this between cases). */
export function resetDemoAgentConfig(): void {
  history = [];
  used = new Set();
  issued = new Map();
  counter = 0;
}

const current = (): { version: number; config: AgentConfig } =>
  history.length ? { version: history[0]!.version, config: history[0]!.config } : { version: 0, config: INITIAL };

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers } });
const fail = (status: number, detail: string, extra: object = {}) => json({ detail, message: "Error de demostración.", ...extra }, status);

/** The change as a full-config patch, or the codes of the fields that fail the (simplified) rules. */
function resolve(body: Record<string, unknown>): { patch: Partial<AgentConfig> } | { status: number; detail: string; fields?: string[] } {
  if (typeof body.rollback_to_version === "number") {
    const target = history.find((h) => h.version === body.rollback_to_version);
    return target ? { patch: target.config } : { status: 422, detail: "unknown_version" };
  }
  const changes = body.changes;
  if (typeof changes !== "object" || changes === null || Array.isArray(changes)) return { status: 422, detail: "invalid_request" };
  const next = { ...current().config, ...changes } as Record<string, unknown>;
  const bad = Object.keys(changes).filter((key) => {
    const v = next[key];
    if (key === "tone") return !["formal", "cercano", "neutral"].includes(String(v));
    if (key === "off_topic_policy") return !["strict", "normal"].includes(String(v));
    if (key === "llm_model") return !MODELS.includes(String(v));
    if (TEXTS.includes(key as ConfigField)) return typeof v !== "string" || v.trim() === "" || v.length > 400 || /https?:\/\/|[<>]/.test(v);
    const ceiling = { daily_token_cap: CEILINGS.max_daily_tokens, daily_cost_cap_micro_usd: CEILINGS.max_daily_cost_micro_usd, chat_rate_limit_per_minute: CEILINGS.max_rate_limit_per_minute }[key];
    return ceiling === undefined || !Number.isInteger(v) || (v as number) < 1 || (v as number) > ceiling;
  });
  return bad.length ? { status: 422, detail: "invalid_config", fields: bad } : { patch: changes as Partial<AgentConfig> };
}

function diffOf(patch: Partial<AgentConfig>, from: AgentConfig): Diff {
  const diff: Diff = {};
  for (const [key, value] of Object.entries(patch)) {
    const old = from[key as ConfigField];
    if (old !== value) diff[key] = [old as DiffValue, value as DiffValue];
  }
  return diff;
}

function warningsOf(diff: Diff, estimate: number | null, free = false) {
  const w = (code: string, severity: "info" | "warning" | "danger", message_es: string) => ({ code, severity, message_es });
  const raised = (k: string) => k in diff && (diff[k]![1] as number) > (diff[k]![0] as number);
  const out = [w("immediate_effect", "info", "Este cambio afecta cada conversación nueva de inmediato y puede aumentar el costo.")];
  if (raised("daily_token_cap") || raised("daily_cost_cap_micro_usd")) out.push(w("cap_raised", "warning", "Subiste un tope diario: el agente podrá gastar más."));
  if (raised("chat_rate_limit_per_minute")) out.push(w("rate_limit_raised", "warning", "Subiste el límite por minuto del chat."));
  if ("llm_model" in diff) out.push(w("model_changed", "danger", "Cambia el modelo del agente: la calidad y el costo pueden variar."));
  if (TEXTS.some((k) => k in diff)) out.push(w("texts_changed", "info", "Cambian los textos que ven los clientes."));
  if ("tone" in diff || "off_topic_policy" in diff) out.push(w("behavior_changed", "warning", "Cambia el tono o la política de temas fuera de alcance."));
  if (free) out.push(w("free_model_limits", "info", "Los modelos gratuitos pueden tener límites de uso del proveedor, menor disponibilidad y calidad distinta; el tope de costo no aplica, el tope de tokens sí."));
  if (estimate === null && ("llm_model" in diff || raised("daily_cost_cap_micro_usd"))) out.push(w("cost_unknown", "warning", "No se puede estimar el costo del modelo seleccionado."));
  return out;
}

const parse = (init?: RequestInit): Record<string, unknown> | null => {
  try {
    const body: unknown = JSON.parse(String(init?.body));
    return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
};

function view() {
  const { version, config } = current();
  return {
    version,
    config,
    ceilings: CEILINGS,
    allowed_models: MODELS,
    model_in_use: MODEL_IN_USE,
    defaults_out_of_bounds: [],
    updated_at: history[0]?.at ?? null,
    updated_by: history.length ? "demo-admin" : null,
  };
}

export function agentConfigRoute(pathname: string, init: RequestInit | undefined, search: URLSearchParams, demoPassword: string): Response {
  const method = init?.method ?? "GET";
  if (pathname === "/admin/agent-config" && method === "GET") return json(view());
  if (pathname === "/admin/agent-config/history" && method === "GET") {
    const limit = Math.min(Math.max(Number(search.get("limit") ?? 20) || 20, 1), 100);
    return json(history.slice(0, limit).map((h) => ({ version: h.version, created_at: h.at, created_by: "demo-admin", note: h.note, action: h.action, diff: h.diff })));
  }
  const apply = pathname === "/admin/agent-config/apply" && method === "PUT";
  if (!apply && !(pathname === "/admin/agent-config/preview" && method === "POST")) return fail(404, "not_found");
  const body = parse(init);
  if (!body || typeof body.base_version !== "number") return fail(422, "invalid_request");
  if (body.base_version !== current().version) return fail(409, "version_conflict");
  const plan = resolve(body);
  if ("detail" in plan) return fail(plan.status, plan.detail, plan.fields ? { fields: plan.fields } : {});
  const diff = diffOf(plan.patch, current().config);
  if (Object.keys(diff).length === 0) return fail(422, "no_changes");
  const technical = Object.keys(diff).some((k) => k === "llm_model" || k.endsWith("_cap") || k.endsWith("_micro_usd") || k.endsWith("_per_minute"));
  const key = JSON.stringify(diff);

  if (!apply) {
    const token = `demo-confirm-${++counter}`;
    issued.set(token, key);
    const model = plan.patch.llm_model ?? current().config.llm_model;
    const estimate = isFree(model) ? 0 : "llm_model" in diff || MODEL_IN_USE.input_price_per_mtok === 0 ? null : (plan.patch.daily_cost_cap_micro_usd ?? current().config.daily_cost_cap_micro_usd);
    return json({
      action: typeof body.rollback_to_version === "number" ? "rollback" : "save",
      base_version: body.base_version,
      diff,
      warnings: warningsOf(diff, estimate, isFree(model) && technical),
      requires_password: technical,
      max_daily_cost_estimate_micro_usd: estimate,
      confirmation_token: token,
      expires_at: new Date(Date.now() + 300_000).toISOString(),
    });
  }
  if (body.typed_confirmation !== "APLICAR") return fail(422, "typed_confirmation_invalid");
  const token = String(body.confirmation_token);
  if (used.has(token)) return fail(403, "token_used");
  if (issued.get(token) !== key) return fail(403, issued.has(token) ? "token_mismatch" : "token_invalid");
  if (technical && body.password === undefined) return fail(422, "password_required");
  if (technical && body.password !== demoPassword) return fail(403, "reauth_failed");
  used.add(token);
  const version = current().version + 1;
  const at = new Date().toISOString();
  const config = { ...current().config, ...plan.patch };
  history.unshift({ version, config, note: typeof body.note === "string" && body.note ? body.note : null, action: typeof body.rollback_to_version === "number" ? "rollback" : "save", diff, at });
  return json({ version, config, applied_at: at });
}
