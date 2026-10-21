import { beforeEach, describe, expect, it, vi } from "vitest";
import { parseApplied, parseConfigView, parseHistory, parsePreview } from "../api/adminAgentConfig";
import { createFakeFetch, DEMO_PASSWORD, resetDemoCatalog } from "./fakeApi";

const fake = createFakeFetch({ latencyMs: 0 });
const call = (method: string, path: string, body?: unknown, token = "demo.admin.token") =>
  fake(`https://api.example/admin/agent-config${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

async function preview(changes: object, base_version = 0) {
  const response = await call("POST", "/preview", { changes, base_version });
  return { response, body: (await response.json()) as unknown };
}
const apply = (changes: object, token: string, extra: object = {}, base_version = 0) =>
  call("PUT", "/apply", { changes, base_version, confirmation_token: token, typed_confirmation: "APLICAR", ...extra });

beforeEach(() => {
  vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  resetDemoCatalog();
});

describe("fake agent config API", () => {
  it("serves a view and previews that satisfy the contract parsers", async () => {
    expect(parseConfigView(await (await call("GET", "")).json()).version).toBe(0);
    const { body } = await preview({ daily_token_cap: 300_000 });
    const parsed = parsePreview(body);
    expect(parsed).toMatchObject({ requires_password: true, max_daily_cost_estimate_micro_usd: null });
    expect(parsed.diff).toEqual({ daily_token_cap: [200_000, 300_000] });
  });

  it("applies with the right password once, then keeps history and rolls back", async () => {
    const changes = { daily_token_cap: 300_000 };
    const token = parsePreview((await preview(changes)).body).confirmation_token;

    expect((await apply(changes, token)).status).toBe(422); // password missing
    expect((await apply(changes, token, { password: "wrong" })).status).toBe(403);
    const ok = await apply(changes, token, { password: DEMO_PASSWORD });
    expect(parseApplied(await ok.json()).version).toBe(1);

    const second = { daily_token_cap: 400_000 };
    const t2 = parsePreview((await preview(second, 1)).body).confirmation_token;
    expect((await apply(second, t2, { password: DEMO_PASSWORD }, 1)).status).toBe(200);

    const back = parsePreview(await (await call("POST", "/preview", { rollback_to_version: 1, base_version: 2 })).json());
    expect([back.action, back.diff]).toEqual(["rollback", { daily_token_cap: [400_000, 300_000] }]);
    const done = await call("PUT", "/apply", { rollback_to_version: 1, base_version: 2, confirmation_token: back.confirmation_token, typed_confirmation: "APLICAR", password: DEMO_PASSWORD });
    expect(parseApplied(await done.json()).config.daily_token_cap).toBe(300_000);
    const history = parseHistory(await (await call("GET", "/history?limit=5")).json());
    expect(history.map((h) => [h.version, h.action])).toEqual([[3, "rollback"], [2, "save"], [1, "save"]]);
  });

  it.each([
    ["stale base version", { tone: "formal" }, 3, 409, "version_conflict"],
    ["unknown model", { llm_model: "x/y" }, 0, 422, "invalid_config"],
    ["a link in a text", { welcome_message: "ver https://x.com" }, 0, 422, "invalid_config"],
    ["identical values", { tone: "cercano" }, 0, 422, "no_changes"],
  ])("refuses %s", async (_name, changes, base, status, detail) => {
    const { response, body } = await preview(changes, base);
    expect([response.status, (body as { detail: string }).detail]).toEqual([status, detail]);
  });

  it("keeps the route admin only", async () => {
    expect((await call("GET", "", undefined, "demo.client.token")).status).toBe(403);
    expect((await call("GET", "", undefined, "nope")).status).toBe(401);
  });
});
