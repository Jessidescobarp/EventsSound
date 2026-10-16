import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { es } from "../copy/es";
import { createFakeFetch } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";

const t = es.securityAdmin;

beforeEach(() => {
  window.sessionStorage.setItem(
    "eventsound.session",
    JSON.stringify({ token: "demo.admin.token", role: "admin", expiresAt: Date.now() + 3_600_000 }),
  );
});

/** The fake API for everything except /admin/security, which answers `body`. */
const security = (body: unknown, status = 200): typeof fetch => {
  const fake = createFakeFetch({ latencyMs: 0 });
  return (input, init) =>
    String(input).includes("/admin/security") ? Promise.resolve(Response.json(body, { status })) : fake(input, init);
};

describe("security admin", () => {
  it("shows the lead, the 24-hour summary and a page of events", async () => {
    renderApp("/admin/seguridad");

    const table = await screen.findByRole("table", { name: t.caption });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 10);
    expect(within(table).getAllByText(t.kinds.chat_refused!).length).toBeGreaterThan(0);
    expect(within(table).getAllByText(t.kinds.login_failed!).length).toBeGreaterThan(0);
    expect(screen.getByText(t.lead)).toBeInTheDocument();
    expect(screen.getByText(`${t.kinds.chat_refused}: 8`, { exact: false })).toBeInTheDocument();
    expect(screen.getByText(`${t.kinds.login_failed}: 4`, { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: t.tab })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText(es.records.pageOf(1, 2), { exact: false })).toBeInTheDocument();
  });

  it("explains an empty log", async () => {
    renderApp(
      "/admin/seguridad",
      security({ items: [], total: 0, limit: 10, offset: 0, last_24h: { chat_refused: 0, login_failed: 0 } }),
    );

    expect(await screen.findByText(t.empty)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("offers a retry when the server refuses", async () => {
    renderApp("/admin/seguridad", security({ detail: "forbidden", message: "No tienes permiso." }, 403));

    expect(await screen.findByRole("alert")).toHaveTextContent(es.records.errorTitle);
    expect(screen.getByRole("button", { name: es.common.retry })).toBeInTheDocument();
  });
});
