import {
  MAX_TEXT_CHARS,
  MICRO_PER_USD,
  TEXT_FIELDS,
  type AgentConfig,
  type AgentConfigView,
  type ConfigField,
} from "../api/adminAgentConfig";

/** Form values as typed: numbers stay strings, the cost cap is shown in USD. */
export interface AgentDraft {
  tone: string;
  off_topic_policy: string;
  refusal_message: string;
  closing_message: string;
  welcome_message: string;
  llm_model: string;
  daily_token_cap: string;
  daily_cost_cap_usd: string;
  chat_rate_limit_per_minute: string;
}

export type FieldProblem = "required" | "too_long" | "url" | "markup" | "digits" | "money" | "range" | "number" | "model";

/** USD text for a micro-USD amount: 2500000 -> "2.5". */
export function microToUsd(micro: number): string {
  const whole = Math.floor(micro / MICRO_PER_USD);
  const frac = String(micro % MICRO_PER_USD).padStart(6, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : String(whole);
}

/** Micro-USD for a decimal text (dot or comma, up to 6 decimals), or null when it is not an amount. */
export function usdToMicro(text: string): number | null {
  const m = /^(\d{1,7})(?:[.,](\d{1,6}))?$/.exec(text.trim());
  return m ? Number(m[1]) * MICRO_PER_USD + Number((m[2] ?? "").padEnd(6, "0")) : null;
}

export function draftOf(config: AgentConfig): AgentDraft {
  const { daily_cost_cap_micro_usd, daily_token_cap, chat_rate_limit_per_minute, ...rest } = config;
  return {
    ...rest,
    daily_token_cap: String(daily_token_cap),
    daily_cost_cap_usd: microToUsd(daily_cost_cap_micro_usd),
    chat_rate_limit_per_minute: String(chat_rate_limit_per_minute),
  };
}

const URL_LIKE = /https?:\/\/|www\.|\b[\w-]+\.[a-z]{2,}\b/i;
const MARKUP = /[<>[\]`&]/;
const DIGITS_MONEY = /[\d$%]/;
const MONEY = /[$%]/;

/** Client-side mirror of the text rules; the server decides. Welcome may carry digits, not $ or %. */
export function textProblem(field: (typeof TEXT_FIELDS)[number], value: string): FieldProblem | null {
  const text = value.trim();
  if (text.length === 0) return "required";
  if (Array.from(text).length > MAX_TEXT_CHARS) return "too_long";
  if (URL_LIKE.test(text)) return "url";
  if (MARKUP.test(text)) return "markup";
  if (field === "welcome_message" ? MONEY.test(text) : DIGITS_MONEY.test(text)) return "digits";
  return null;
}

const intProblem = (text: string, ceiling: number): FieldProblem | null => {
  if (!/^\d{1,12}$/.test(text.trim())) return "number";
  const n = Number(text);
  return n >= 1 && n <= ceiling ? null : "range";
};

export interface FormResult {
  /** Only the fields that differ from the loaded config, in contract units. */
  changes: Partial<AgentConfig>;
  problems: Partial<Record<keyof AgentDraft, FieldProblem>>;
}

/** Validates every field (a field already out of bounds must be fixed too) and collects the changed ones. */
export function evaluateDraft(draft: AgentDraft, view: AgentConfigView): FormResult {
  const { config, ceilings } = view;
  const problems: FormResult["problems"] = {};
  const changes: Record<string, unknown> = {};
  const change = (key: ConfigField, value: unknown) => {
    if (value !== config[key]) changes[key] = value;
  };

  change("tone", draft.tone);
  change("off_topic_policy", draft.off_topic_policy);
  if (!view.allowed_models.includes(draft.llm_model)) problems.llm_model = "model";
  else change("llm_model", draft.llm_model);
  for (const field of TEXT_FIELDS) {
    const problem = textProblem(field, draft[field]);
    if (problem) problems[field] = problem;
    else change(field, draft[field].trim());
  }
  const tokens = intProblem(draft.daily_token_cap, ceilings.max_daily_tokens);
  if (tokens) problems.daily_token_cap = tokens;
  else change("daily_token_cap", Number(draft.daily_token_cap));
  const rate = intProblem(draft.chat_rate_limit_per_minute, ceilings.max_rate_limit_per_minute);
  if (rate) problems.chat_rate_limit_per_minute = rate;
  else change("chat_rate_limit_per_minute", Number(draft.chat_rate_limit_per_minute));
  const micro = usdToMicro(draft.daily_cost_cap_usd);
  if (micro === null) problems.daily_cost_cap_usd = "money";
  else if (micro < 1 || micro > ceilings.max_daily_cost_micro_usd) problems.daily_cost_cap_usd = "range";
  else change("daily_cost_cap_micro_usd", micro);

  return { changes: changes as Partial<AgentConfig>, problems };
}
