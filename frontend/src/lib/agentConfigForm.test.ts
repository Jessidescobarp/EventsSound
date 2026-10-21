import { describe, expect, it } from "vitest";
import { parseConfigView } from "../api/adminAgentConfig";
import { VIEW } from "../test/agentConfigFixtures";
import { draftOf, evaluateDraft, microToUsd, textProblem, usdToMicro } from "./agentConfigForm";

const view = parseConfigView(VIEW);
const draft = draftOf(view.config);

describe("USD conversion", () => {
  it.each([
    ["2", 2_000_000],
    ["0.5", 500_000],
    [" 1,25 ", 1_250_000],
    ["0.000001", 1],
    ["1.1234567", null],
    ["-1", null],
    ["1e3", null],
    ["", null],
  ])("usdToMicro(%j) = %j", (text, micro) => {
    expect(usdToMicro(text)).toBe(micro);
  });

  it.each([[2_000_000, "2"], [500_000, "0.5"], [1, "0.000001"], [10_000_000, "10"]])("microToUsd(%i) = %s", (micro, usd) => {
    expect(microToUsd(micro)).toBe(usd);
    expect(usdToMicro(usd)).toBe(micro);
  });
});

describe("textProblem", () => {
  it.each([
    ["refusal_message", "Solo cotizaciones.", null],
    ["refusal_message", "   ", "required"],
    ["refusal_message", "x".repeat(401), "too_long"],
    ["refusal_message", "Visita https://x.com", "url"],
    ["refusal_message", "Escribe a ayuda.co", "url"],
    ["closing_message", "Usa <b>negrita</b>", "markup"],
    ["closing_message", "Llama al 300", "digits"],
    ["refusal_message", "Cuesta 50%", "digits"],
    ["welcome_message", "Hola, tenemos 3 paquetes.", null],
    ["welcome_message", "Desde $5", "digits"],
  ] as const)("%s %j -> %s", (field, value, expected) => {
    expect(textProblem(field, value)).toBe(expected);
  });
});

describe("evaluateDraft", () => {
  it("sends nothing for an untouched form", () => {
    expect(evaluateDraft(draft, view)).toEqual({ changes: {}, problems: {} });
  });

  it("sends only changed fields in contract units", () => {
    const result = evaluateDraft(
      { ...draft, tone: "formal", daily_cost_cap_usd: "3.5", welcome_message: "  Hola.  ", llm_model: "vendor/model-b" },
      view,
    );
    expect(result.changes).toEqual({
      tone: "formal",
      daily_cost_cap_micro_usd: 3_500_000,
      welcome_message: "Hola.",
      llm_model: "vendor/model-b",
    });
    expect(result.problems).toEqual({});
  });

  it.each([
    ["daily_token_cap", "1000001", "range"],
    ["daily_token_cap", "0", "range"],
    ["daily_token_cap", "abc", "number"],
    ["chat_rate_limit_per_minute", "61", "range"],
    ["daily_cost_cap_usd", "10.000001", "range"],
    ["daily_cost_cap_usd", "x", "money"],
    ["llm_model", "other/model", "model"],
  ] as const)("flags %s=%s as %s and does not send it", (field, value, problem) => {
    const result = evaluateDraft({ ...draft, [field]: value }, view);
    expect(result.problems[field]).toBe(problem);
    expect(Object.keys(result.changes)).toHaveLength(0);
  });

  it("still flags a stored value that is out of bounds (defaults at version 0)", () => {
    const zero = parseConfigView({ ...VIEW, version: 0, defaults_out_of_bounds: ["daily_token_cap"], config: { ...VIEW.config, daily_token_cap: 0 } });
    expect(evaluateDraft(draftOf(zero.config), zero).problems.daily_token_cap).toBe("range");
  });
});
