import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { es } from "../copy/es";
import { resetDemoCatalog } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";

const t = es.catalogAdmin;

beforeEach(() => {
  resetDemoCatalog();
  window.sessionStorage.setItem(
    "eventsound.session",
    JSON.stringify({ token: "demo.admin.token", role: "admin", expiresAt: Date.now() + 3_600_000 }),
  );
});

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const itemsTable = () => screen.findByRole("table", { name: t.itemsCaption });
const goPackages = async () => {
  await itemsTable();
  fireEvent.click(screen.getByRole("tab", { name: t.packagesTitle }));
  return screen.findByRole("table", { name: t.packagesCaption });
};
const fetchCalls = () => (globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length;
const click = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

describe("catalog admin: tabs and dialog", () => {
  it("switches lists with the tabs, items first", async () => {
    renderApp("/admin/catalogo");
    await itemsTable();
    expect(screen.getByRole("tab", { name: t.itemsTitle })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("table", { name: t.packagesCaption })).toBeNull();

    await goPackages();
    expect(screen.getByRole("tab", { name: t.packagesTitle })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("table", { name: t.itemsCaption })).toBeNull();
    expect(screen.getByRole("button", { name: t.newPackage })).toBeInTheDocument();
  });

  it("opens the edit form prefilled in a dialog and cancel closes it without saving", async () => {
    renderApp("/admin/catalogo");
    await itemsTable();
    const calls = fetchCalls();

    fireEvent.click(screen.getByRole("button", { name: t.editLabel("Máquina de humo") }));
    const dialog = screen.getByRole("dialog", { name: t.itemFormEdit });
    expect(within(dialog).getByLabelText(t.name)).toHaveValue("Máquina de humo");
    click(t.cancel);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(t.saved)).toBeNull();
    expect(fetchCalls()).toBe(calls);
  });

  it("closes on Escape and keeps the selected tab", async () => {
    renderApp("/admin/catalogo");
    await goPackages();

    click(t.newPackage);
    fireEvent.keyDown(screen.getByRole("dialog", { name: t.packageFormNew }), { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("tab", { name: t.packagesTitle })).toHaveAttribute("aria-selected", "true");
  });
});

describe("catalog admin: items", () => {
  it("creates an item and lists it, telling the admin the assistant will use it", async () => {
    renderApp("/admin/catalogo");
    await itemsTable();

    click(t.newItem);
    fill(t.code, "sound_nuevo");
    fill(t.name, "Parlante nuevo de prueba");
    fill(t.stock, "6");
    fill(t.price, "99000");
    click(t.save);

    expect(await screen.findByText(t.saved)).toBeInTheDocument();
    const table = await itemsTable();
    expect(within(table).getByText("Parlante nuevo de prueba")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("edits an item keeping its code fixed", async () => {
    renderApp("/admin/catalogo");
    await itemsTable();

    fireEvent.click(screen.getByRole("button", { name: t.editLabel("Máquina de humo") }));
    expect(screen.getByLabelText(t.code)).toBeDisabled();
    fill(t.stock, "0");
    click(t.save);

    await screen.findByText(t.saved);
    const row = within(await itemsTable()).getByText("Máquina de humo").closest("tr") as HTMLElement;
    expect(within(row).getByText("0")).toBeInTheDocument();
  });

  it("explains a taken code and keeps the form open", async () => {
    renderApp("/admin/catalogo");
    await itemsTable();

    click(t.newItem);
    fill(t.code, "dj_booth");
    fill(t.name, "Duplicado");
    click(t.save);

    expect(await screen.findByRole("alert")).toHaveTextContent(t.failures.code_taken ?? "");
    expect(screen.getByLabelText(t.code)).toHaveValue("dj_booth");
  });

  it("flags bad fields without sending anything", async () => {
    renderApp("/admin/catalogo");
    await itemsTable();
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length;

    click(t.newItem);
    fill(t.code, "Mal Codigo");
    fill(t.price, "-5");
    click(t.save);

    expect(screen.getByText(t.errors.code)).toBeInTheDocument();
    expect(screen.getByText(t.errors.price)).toBeInTheDocument();
    expect((globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(calls);
  });
});

describe("catalog admin: packages", () => {
  it("creates a package from two items, then edits its discount", async () => {
    renderApp("/admin/catalogo");
    await goPackages();

    click(t.newPackage);
    fill(t.code, "pkg_prueba");
    fill(t.name, "Paquete de prueba");
    fill(t.discount, "7.5");
    fireEvent.change(screen.getAllByLabelText(t.lineItem)[0] as HTMLElement, { target: { value: "dj_booth" } });
    click(t.addLine);
    fireEvent.change(screen.getAllByLabelText(t.lineItem)[1] as HTMLElement, { target: { value: "effects_fog_machine" } });
    click(t.save);

    await screen.findByText(t.saved);
    const table = await screen.findByRole("table", { name: t.packagesCaption });
    const row = within(table).getByText("Paquete de prueba").closest("tr") as HTMLElement;
    expect(within(row).getByText("7.5%")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: t.editLabel("Paquete de prueba") }));
    fill(t.discount, "10");
    click(t.save);
    await screen.findByText(t.saved); // opening the form cleared the first confirmation
    const table2 = await screen.findByRole("table", { name: t.packagesCaption });
    const edited = within(table2).getByText("Paquete de prueba").closest("tr") as HTMLElement;
    expect(within(edited).getByText("10%")).toBeInTheDocument();
  });

  it("refuses a package with no item chosen", async () => {
    renderApp("/admin/catalogo");
    await goPackages();

    click(t.newPackage);
    fill(t.code, "pkg_vacio");
    fill(t.name, "Vacío");
    click(t.save);

    expect(screen.getByText(t.errors.lines)).toBeInTheDocument();
  });
});
