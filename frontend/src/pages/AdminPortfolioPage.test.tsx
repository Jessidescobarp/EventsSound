import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { es } from "../copy/es";
import { resetDemoCatalog } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";

const t = es.portfolioAdmin;

beforeEach(() => {
  resetDemoCatalog();
  window.sessionStorage.setItem(
    "eventsound.session",
    JSON.stringify({ token: "demo.admin.token", role: "admin", expiresAt: Date.now() + 3_600_000 }),
  );
});

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const table = () => screen.findByRole("table", { name: t.caption });

describe("portfolio admin", () => {
  it("creates an event that then shows on the public page", async () => {
    renderApp("/admin/portafolio");
    await table();

    fireEvent.click(screen.getByRole("button", { name: t.newEvent }));
    fill(t.title, "Boda en la finca");
    fill(t.kind, "Boda");
    fill(t.description, "Sonido y luces para 120 invitados.");
    fill(t.equipment, "Sonido\nLuces LED");
    fireEvent.click(screen.getByRole("button", { name: es.catalogAdmin.save }));

    expect(await screen.findByText(es.catalogAdmin.saved)).toBeInTheDocument();
    expect(within(await table()).getByText("Boda en la finca")).toBeInTheDocument();
  });

  it("hides an event: it stays in the admin list but leaves the public page", async () => {
    const view = renderApp("/admin/portafolio");
    const list = await table();
    fireEvent.click(within(list).getByRole("button", { name: es.catalogAdmin.editLabel("Concierto en teatro") }));
    fireEvent.click(screen.getByLabelText(t.visible));
    fireEvent.click(screen.getByRole("button", { name: es.catalogAdmin.save }));
    await screen.findByText(es.catalogAdmin.saved);

    const row = within(await table()).getByText("Concierto en teatro").closest("tr") as HTMLElement;
    expect(within(row).getByText(t.hidden)).toBeInTheDocument();
    view.unmount();

    renderApp("/portafolio");
    await screen.findByRole("heading", { level: 2, name: "Boda en jardín" });
    expect(screen.queryByRole("heading", { level: 2, name: "Concierto en teatro" })).toBeNull();
  });

  it("flags bad fields without sending anything", async () => {
    renderApp("/admin/portafolio");
    await table();
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: t.newEvent }));
    fill(t.title, "   ");
    fireEvent.click(screen.getByRole("button", { name: es.catalogAdmin.save }));

    expect(screen.getByText(t.errors.title)).toBeInTheDocument();
    expect((globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(calls);
  });
});
