import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { es } from "../copy/es";
import { createFakeFetch, DEMO_PASSWORD, resetDemoCatalog } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";

const t = es.agentAdmin;
const c = t.confirm;
const h = t.history;

const fake = createFakeFetch({ latencyMs: 0 });
const api = async (method: string, path: string, body: object) => {
  const response = await fake(`https://api.example/admin/agent-config${path}`, {
    method,
    headers: { Authorization: "Bearer demo.admin.token" },
    body: JSON.stringify(body),
  });
  return (await response.json()) as Record<string, string>;
};
/** Saves `changes` as the next version through the fake API, the way the UI would. */
async function seed(changes: object, base_version: number, note?: string) {
  const { confirmation_token } = await api("POST", "/preview", { changes, base_version });
  await api("PUT", "/apply", { changes, base_version, confirmation_token, typed_confirmation: "APLICAR", password: DEMO_PASSWORD, note });
}

beforeEach(() => {
  resetDemoCatalog();
  window.sessionStorage.setItem(
    "eventsound.session",
    JSON.stringify({ token: "demo.admin.token", role: "admin", expiresAt: Date.now() + 3_600_000 }),
  );
});

const rows = async () => within(await screen.findByRole("table", { name: h.caption })).getAllByRole("row").slice(1);

describe("history and rollback", () => {
  it("explains an empty history", async () => {
    renderApp("/admin/agente");
    expect(await screen.findByText(h.empty)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("lists versions newest first with a compact diff, and offers restore on the old ones only", async () => {
    await seed({ daily_token_cap: 300_000 }, 0, "<b>subida</b>");
    await seed({ tone: "formal" }, 1);
    const { container } = renderApp("/admin/agente");

    const [newest, oldest] = await rows();
    expect(newest).toHaveTextContent(`${t.fields.tone}: ${t.tones.cercano} → ${t.tones.formal}`);
    expect(within(newest!).getByText(h.current)).toBeInTheDocument();
    expect(within(newest!).queryByRole("button")).toBeNull();
    expect(oldest).toHaveTextContent("<b>subida</b>"); // shown as text
    expect(container.querySelector("table b")).toBeNull();
    expect(within(oldest!).getByRole("button", { name: h.restoreLabel(1) })).toHaveTextContent(h.restore);
  });

  it("restores a version through the same preview and confirmation, using rollback_to_version", async () => {
    await seed({ daily_token_cap: 300_000 }, 0);
    await seed({ daily_token_cap: 400_000 }, 1);
    renderApp("/admin/agente");

    await rows();
    fireEvent.click(screen.getByRole("button", { name: h.restoreLabel(1) }));
    await screen.findByRole("dialog", { name: c.reviewTitle });
    const calls = vi.mocked(fetch).mock.calls as [string, RequestInit][];
    const preview = calls.find(([url, init]) => url.endsWith("/preview") && String(init.body).includes("rollback"));
    expect(JSON.parse(String(preview?.[1].body))).toEqual({ rollback_to_version: 1, base_version: 2 });
    expect(screen.getByText(`${t.diffTo}: 300000`)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: c.continue }));
    fireEvent.change(await screen.findByLabelText(c.typeLabel("APLICAR")), { target: { value: "APLICAR" } });
    fireEvent.change(screen.getByLabelText(c.passwordLabel), { target: { value: DEMO_PASSWORD } });
    fireEvent.click(screen.getByRole("button", { name: c.apply }));

    expect(await screen.findByText(c.applied(3))).toBeInTheDocument();
    const [top] = await rows();
    expect(top).toHaveTextContent(h.actions.rollback!);
    expect(within(top!).getByText(h.current)).toBeInTheDocument();
  });
});
