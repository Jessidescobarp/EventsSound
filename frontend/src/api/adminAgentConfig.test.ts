import { describe, expect, it } from "vitest";
import {
  classifyConfigError,
  parseApplied,
  parseConfigView,
  parseHistory,
  parsePreview,
} from "./adminAgentConfig";
import { CONFIG, ITEM, PREVIEW, VIEW } from "../test/agentConfigFixtures";
import { ApiError } from "./client";

const bad = (value: unknown, patch: Record<string, unknown>) => ({ ...(value as object), ...patch });

describe("agent config parsers", () => {
  it("accepts valid payloads and tolerates extra fields", () => {
    expect(parseConfigView(VIEW).config).toEqual(CONFIG);
    const legacy: Record<string, unknown> = { ...VIEW.model_in_use }; // an older server sends no `free`
    delete legacy.free;
    expect(parseConfigView({ ...VIEW, model_in_use: legacy }).model_in_use.free).toBe(false);
    expect(parseConfigView({ ...VIEW, model_in_use: { ...legacy, free: true } }).model_in_use.free).toBe(true);
    expect(parsePreview(bad(PREVIEW, { more: 1 })).max_daily_cost_estimate_micro_usd).toBeNull();
    expect(parseApplied({ version: 4, config: CONFIG, applied_at: "2026-10-21T10:00:00Z" }).version).toBe(4);
    expect(parseHistory([ITEM])[0]!.diff).toEqual({ tone: [null, "formal"] });
  });

  it.each([
    ["view missing config", () => parseConfigView({ ...VIEW, config: undefined })],
    ["view unknown tone", () => parseConfigView(bad(VIEW, { config: { ...CONFIG, tone: "rude" } }))],
    ["view string cap", () => parseConfigView(bad(VIEW, { config: { ...CONFIG, daily_token_cap: "9" } }))],
    ["view bad status", () => parseConfigView(bad(VIEW, { model_in_use: { ...VIEW.model_in_use, status: "on" } }))],
    ["view free not a boolean", () => parseConfigView(bad(VIEW, { model_in_use: { ...VIEW.model_in_use, free: "yes" } }))],
    ["view models not a list", () => parseConfigView(bad(VIEW, { allowed_models: "x" }))],
    ["preview unknown severity", () => parsePreview(bad(PREVIEW, { warnings: [{ code: "a", severity: "loud", message_es: "x" }] }))],
    ["preview diff not a pair", () => parsePreview(bad(PREVIEW, { diff: { tone: ["a"] } }))],
    ["preview diff object value", () => parsePreview(bad(PREVIEW, { diff: { tone: [{}, "a"] } }))],
    ["preview estimate as string", () => parsePreview(bad(PREVIEW, { max_daily_cost_estimate_micro_usd: "1" }))],
    ["preview without token", () => parsePreview(bad(PREVIEW, { confirmation_token: undefined }))],
    ["history not a list", () => parseHistory({})],
    ["history unknown action", () => parseHistory([{ ...ITEM, action: "delete" }])],
  ])("rejects %s", (_name, run) => {
    expect(run).toThrow();
  });
});

const err = (status: number, detail?: string, code: ApiError["code"] = "http") => new ApiError(code, "x", status, { detail });

describe("classifyConfigError", () => {
  it.each([
    [err(401, "not_authenticated"), "unauthenticated"],
    [err(403, "forbidden"), "forbidden"],
    [err(403), "forbidden"],
    [err(403, "reauth_failed"), "reauth_failed"],
    [err(403, "token_used"), "token_stale"],
    [err(403, "token_expired"), "token_stale"],
    [err(403, "token_mismatch"), "token_stale"],
    [err(409, "version_conflict"), "version_conflict"],
    [err(422, "invalid_config"), "invalid_config"],
    [err(422, "typed_confirmation_invalid"), "typed_confirmation"],
    [err(422, "password_required"), "password_required"],
    [err(429, "rate_limited"), "rate_limited"],
    [err(429), "rate_limited"],
    [err(503, "confirmation_unavailable", "server"), "confirmation_unavailable"],
    [err(503, "storage_unavailable", "server"), "unavailable"],
    [err(502, undefined, "server"), "transient"],
    [err(400, "constructor"), "unexpected"],
    [new ApiError("aborted", "x"), "aborted"],
    [new Error("boom"), "unexpected"],
  ])("maps %# to %s", (error, expected) => {
    expect(classifyConfigError(error)).toBe(expected);
  });
});
