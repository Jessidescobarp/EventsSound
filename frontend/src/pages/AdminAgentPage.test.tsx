import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { es } from "../copy/es";
import { createFakeFetch, resetDemoCatalog } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";
import { VIEW } from "../test/agentConfigFixtures";

const t = es.agentAdmin;

const signIn = (role: "admin" | "client") =>
  window.sessionStorage.setItem(
    "eventsound.session",
    JSON.stringify({ token: `demo.${role}.token`, role, expiresAt: Date.now() + 3_600_000 }),
  );
beforeEach(() => {
  resetDemoCatalog();
  signIn("admin");
});

/** Fake API, except that GET /admin/agent-config answers `view`. */
const withView = (view: object, status = 200): typeof fetch => {
  const fake = createFakeFetch({ latencyMs: 0 });
  return (input, init) =>
    String(input).endsWith("/admin/agent-config") ? Promise.resolve(Response.json(view, { status })) : fake(input, init);
};
const card = () => screen.findByRole("heading", { name: t.card.title });

describe("agent tab: routing and role", () => {
  it("shows the tab to an admin and keeps it selected", async () => {
    renderApp("/admin/agente");
    await card();
    expect(screen.getByRole("link", { name: t.tab })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText(t.warningTitle)).toBeInTheDocument();
  });

  it("does not render the tab content for a client", async () => {
    signIn("client");
    renderApp("/admin/agente");
    expect(await screen.findByText(es.auth.forbiddenTitle)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: t.card.title })).toBeNull();
  });

  it.each([
    [403, { detail: "forbidden" }, t.loadError],
    [200, { ...VIEW, config: null }, t.loadError],
  ])("offers a retry when the answer is %i and unusable", async (status, body, title) => {
    renderApp("/admin/agente", withView(body, status));
    expect(await screen.findByRole("alert")).toHaveTextContent(title);
    expect(screen.getByRole("button", { name: es.common.retry })).toBeInTheDocument();
  });
});

describe("model in use card", () => {
  it.each([
    ["active", { status: "active" }, t.card.statuses.active, false],
    ["disabled", { status: "disabled" }, t.card.statuses.disabled, false],
    ["replay without prices", { status: "replay", input_price_per_mtok: 0, output_price_per_mtok: 0, cost_cap_applies: false }, t.card.statuses.replay, true],
  ])("%s", async (_name, patch, badge, warns) => {
    renderApp("/admin/agente", withView({ ...VIEW, model_in_use: { ...VIEW.model_in_use, ...patch } }));
    await card();
    expect(screen.getByText(badge!)).toBeInTheDocument();
    expect(screen.queryByText(t.card.capNotApplied, { exact: false }) !== null).toBe(warns);
    expect(screen.getAllByText(t.card.perMillion(warns ? "0" : "3"))).toHaveLength(warns ? 2 : 1);
  });
});

describe("free models", () => {
  it.each([
    ["a free model shows the badge", { model: "vendor/model-b:free", free: true, input_price_per_mtok: 0, output_price_per_mtok: 0, cost_cap_applies: false }, true],
    ["a paid model does not", {}, false],
  ])("%s", async (_name, patch, badge) => {
    renderApp("/admin/agente", withView({ ...VIEW, model_in_use: { ...VIEW.model_in_use, ...patch } }));
    await card();
    expect(screen.queryByText(t.card.free) !== null).toBe(badge);
  });

  it("marks free models in the model select", async () => {
    renderApp("/admin/agente", withView({ ...VIEW, allowed_models: ["vendor/model-a", "vendor/model-b:free", "vendor/env:free"], free_models: ["vendor/model-b:free"] }));
    await card();
    expect(screen.getByRole("option", { name: t.freeModelOption("vendor/model-b:free") })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "vendor/model-a" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "vendor/env:free" })).toBeInTheDocument(); // the server says it is not free
  });

  it("marks paid models in the model select", async () => {
    const models = ["vendor/model-a", "vendor/model-b"];
    renderApp("/admin/agente", withView({ ...VIEW, allowed_models: models, paid_models: ["vendor/model-b"] }));
    await card();
    expect(screen.getByRole("option", { name: t.paidModelOption("vendor/model-b") })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "vendor/model-a" })).toBeInTheDocument();
  });
});
