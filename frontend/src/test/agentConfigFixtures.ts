/** Valid payloads of /admin/agent-config shared by the tests. */
export const CONFIG = {
  tone: "cercano",
  off_topic_policy: "strict",
  refusal_message: "Solo puedo ayudarte con cotizaciones.",
  closing_message: "Gracias por escribirnos.",
  welcome_message: "Hola, te ayudo a cotizar.",
  llm_model: "vendor/model-a",
  daily_token_cap: 200000,
  daily_cost_cap_micro_usd: 2000000,
  chat_rate_limit_per_minute: 10,
};
export const VIEW = {
  version: 3,
  config: CONFIG,
  ceilings: { max_daily_tokens: 1000000, max_daily_cost_micro_usd: 10000000, max_rate_limit_per_minute: 60 },
  allowed_models: ["vendor/model-a", "vendor/model-b"],
  model_in_use: { provider: "openrouter", model: "vendor/model-a", status: "active", input_price_per_mtok: 3, output_price_per_mtok: 15, cost_cap_applies: true },
  defaults_out_of_bounds: [],
  updated_at: "2026-10-20T10:00:00Z",
  updated_by: "abc",
  extra_field: true,
};
export const PREVIEW = {
  action: "save",
  base_version: 3,
  diff: { tone: ["cercano", "formal"] },
  warnings: [{ code: "immediate_effect", severity: "info", message_es: "Aplica de inmediato." }],
  requires_password: false,
  max_daily_cost_estimate_micro_usd: null,
  confirmation_token: "tok.sig",
  expires_at: "2026-10-21T10:05:00Z",
};
export const ITEM = { version: 2, created_at: "2026-10-20T10:00:00Z", created_by: null, note: null, action: "save", diff: { tone: [null, "formal"] } };
