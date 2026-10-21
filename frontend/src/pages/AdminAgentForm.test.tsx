import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { es } from "../copy/es";
import { createFakeFetch, resetDemoCatalog } from "../mocks/fakeApi";
import { VIEW } from "../test/agentConfigFixtures";
import { renderApp } from "../test/renderApp";

const t = es.agentAdmin;

beforeEach(() => {
  resetDemoCatalog();
  window.sessionStorage.setItem(
    "eventsound.session",
    JSON.stringify({ token: "demo.admin.token", role: "admin", expiresAt: Date.now() + 3_600_000 }),
  );
});

/** Fake API, except where `answers` replaces the view or the preview response. */
const withAnswers = (answers: { view?: object; preview?: Response }): typeof fetch => {
  const fake = createFakeFetch({ latencyMs: 0 });
  return (input, init) => {
    const url = String(input);
    if (answers.view && url.endsWith("/admin/agent-config")) return Promise.resolve(Response.json(answers.view));
    if (answers.preview && url.endsWith("/preview")) return Promise.resolve(answers.preview.clone());
    return fake(input, init);
  };
};
const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
const review = () => fireEvent.click(screen.getByRole("button", { name: t.review }));
const form = () => screen.findByRole("form", { name: t.tab });
const previewBody = () => {
  const calls = vi.mocked(fetch).mock.calls as [string, RequestInit][];
  const call = calls.find(([url]) => url.endsWith("/preview"));
  return call ? (JSON.parse(String(call[1].body)) as Record<string, unknown>) : null;
};

describe("agent form", () => {
  it("shows each ceiling and hints the fields that start outside the limits", async () => {
    renderApp("/admin/agente", withAnswers({ view: { ...VIEW, defaults_out_of_bounds: ["daily_token_cap"] } }));
    await form();
    expect(screen.getByText(t.ceiling("10 USD"))).toBeInTheDocument();
    expect(screen.getByText(t.ceiling("60"))).toBeInTheDocument();
    expect(screen.getByText(t.outOfBounds(t.fields.daily_token_cap!))).toBeInTheDocument();
  });

  it("shows the rules and the character counter of a text", async () => {
    renderApp("/admin/agente");
    await form();
    fill(t.fields.welcome_message!, "Hola");
    expect(screen.getByText(`${t.textRules}${t.noMoneyRule} ${t.counter(4, 400)}`)).toBeInTheDocument();
  });

  it("does not call the server when nothing changed", async () => {
    renderApp("/admin/agente");
    await form();
    review();
    expect(await screen.findByText(t.noChanges)).toBeInTheDocument();
    expect(previewBody()).toBeNull();
  });

  it("blocks invalid input client side with inline messages", async () => {
    renderApp("/admin/agente");
    await form();
    fill(t.fields.daily_token_cap!, "99999999");
    fill(t.fields.refusal_message!, "Visita https://x.com");
    review();
    expect(await screen.findByText(t.fixFields)).toBeInTheDocument();
    expect(screen.getByText(t.problems.range!)).toBeInTheDocument();
    expect(screen.getByText(t.problems.url!)).toBeInTheDocument();
    expect(previewBody()).toBeNull();
  });

  it("sends only the changed fields (cost in micro-USD) and opens the review dialog", async () => {
    renderApp("/admin/agente");
    await form();
    fill(t.fields.tone!, "formal");
    fill(t.fields.daily_cost_cap_usd!, "3.5");
    review();

    expect(await screen.findByRole("dialog", { name: t.confirm.reviewTitle })).toBeInTheDocument();
    expect(previewBody()).toEqual({ changes: { tone: "formal", daily_cost_cap_micro_usd: 3_500_000 }, base_version: 0 });
    expect(screen.getByText(`${t.diffTo}: 3.5 USD`)).toBeInTheDocument();
    expect(screen.getByText(`${t.diffTo}: ${t.tones.formal}`)).toBeInTheDocument();
    expect(screen.getByText(t.estimateUnknown)).toBeInTheDocument();
    expect(screen.getAllByText(`${t.severity.warning}:`, { exact: false }).length).toBeGreaterThan(0);
  });

  it("renders diff text as plain text, never as markup", async () => {
    const preview = {
      action: "save", base_version: 0, requires_password: false, max_daily_cost_estimate_micro_usd: 1_500_000,
      diff: { welcome_message: ["a", "<img src=x onerror=alert(1)>"] },
      warnings: [], confirmation_token: "t", expires_at: "2026-10-21T10:05:00Z",
    };
    const { container } = renderApp("/admin/agente", withAnswers({ preview: Response.json(preview) }));
    await form();
    fill(t.fields.tone!, "formal");
    review();
    expect(await screen.findByText(`${t.diffTo}: <img src=x onerror=alert(1)>`)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(t.estimate("1.5"))).toBeInTheDocument();
  });

  it.each([
    [409, { detail: "version_conflict" }, {}, t.errors.version_conflict],
    [422, { detail: "invalid_config", fields: ["daily_token_cap"] }, {}, `${t.errors.invalid_config} ${t.invalidFields(t.fields.daily_token_cap!)}`],
    [429, { detail: "rate_limited" }, { "Retry-After": "12" }, `${t.errors.rate_limited} ${t.retryIn(12)}`],
    [503, { detail: "confirmation_unavailable" }, {}, t.errors.confirmation_unavailable],
    [403, { detail: "forbidden" }, {}, t.errors.forbidden],
  ])("maps a %i answer to a Spanish message", async (status, body, headers, text) => {
    renderApp("/admin/agente", withAnswers({ preview: Response.json(body, { status, headers }) }));
    await form();
    fill(t.fields.tone!, "formal");
    review();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(text));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
