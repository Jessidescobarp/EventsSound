import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { es } from "../copy/es";
import { DEMO_PASSWORD } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";

const ADMIN = "admin@eventsounddr.example";
const CLIENT = "cliente@eventsounddr.example";

beforeEach(() => window.sessionStorage.clear());

async function signIn(email: string, password = DEMO_PASSWORD) {
  fireEvent.change(await screen.findByLabelText(es.auth.email), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(es.auth.password), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: es.auth.submit }));
}

const heading = (name: string) => screen.findByRole("heading", { level: 1, name });

describe("sign in", () => {
  it("sends a signed-out visitor to the login page instead of the protected page", async () => {
    renderApp("/mis-cotizaciones");

    expect(await heading(es.auth.title)).toBeInTheDocument();
  });

  it("shows one generic error for a wrong password and keeps the visitor signed out", async () => {
    renderApp("/ingresar");

    await signIn(CLIENT, "wrong");

    expect(await screen.findByRole("alert")).toHaveTextContent(es.auth.errors.invalid_credentials ?? "");
    expect(window.sessionStorage.getItem("eventsound.session")).toBeNull();
    expect(screen.getByLabelText(es.auth.password)).toHaveValue("wrong");
  });

  it("tells the visitor how long to wait when attempts are limited", async () => {
    renderApp("/ingresar");

    await signIn("limite@eventsounddr.example");

    expect(await screen.findByRole("alert")).toHaveTextContent(es.auth.errors.rate_limited ?? "");
    expect(screen.getByRole("alert")).toHaveTextContent(es.auth.waitSeconds(5));
    expect(screen.getByRole("button", { name: es.auth.submit })).toBeDisabled();
  });

  it("lands a client on their quotes, lists only their own, and offers no admin link", async () => {
    renderApp("/ingresar");

    await signIn(CLIENT);

    expect(await heading(es.records.myTitle)).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: es.records.quotesCaption });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 7); // header + the 7 saved while signed in
    const nav = screen.getByRole("navigation", { name: es.a11y.mainNav });
    expect(within(nav).queryByRole("link", { name: es.nav.admin })).toBeNull();
    expect(within(nav).getByRole("button", { name: es.nav.logout })).toBeInTheDocument();
  });

  it("keeps a client out of the admin area", async () => {
    // A guard decision only: the API is what really refuses (covered by its own tests).
    window.sessionStorage.setItem(
      "eventsound.session",
      JSON.stringify({ token: "demo.client.token", role: "client", expiresAt: Date.now() + 3_600_000 }),
    );

    renderApp("/admin/cotizaciones");

    expect(await screen.findByRole("alert")).toHaveTextContent(es.auth.forbiddenTitle);
  });

  it("signs out: the session is dropped and the login link comes back", async () => {
    renderApp("/ingresar");
    await signIn(CLIENT);
    await heading(es.records.myTitle);

    fireEvent.click(screen.getByRole("button", { name: es.nav.logout }));

    await waitFor(() => expect(window.sessionStorage.getItem("eventsound.session")).toBeNull());
    expect(await heading(es.auth.title)).toBeInTheDocument();
  });
});

describe("admin area", () => {
  it("opens on the quotes tab, pages through them and switches to bookings", async () => {
    renderApp("/ingresar");
    await signIn(ADMIN);

    expect(await heading(es.records.adminTitle)).toBeInTheDocument();
    let table = await screen.findByRole("table", { name: es.records.quotesCaption });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 10);
    expect(within(table).getAllByText(CLIENT).length).toBeGreaterThan(0); // who made the quote
    expect(within(table).getAllByText(es.records.anonymous).length).toBeGreaterThan(0);
    expect(screen.getByText(es.records.pageOf(1, 3), { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: es.records.previous })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: es.records.next }));
    await screen.findByText(es.records.pageOf(2, 3), { exact: false });
    fireEvent.click(screen.getByRole("button", { name: es.records.next }));
    await screen.findByText(es.records.pageOf(3, 3), { exact: false });
    table = screen.getByRole("table", { name: es.records.quotesCaption });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 5);
    expect(screen.getByRole("button", { name: es.records.next })).toBeDisabled();

    fireEvent.click(screen.getByRole("link", { name: es.records.tabBookings }));
    const bookings = await screen.findByRole("table", { name: es.records.bookingsCaption });
    expect(within(bookings).getAllByRole("row")).toHaveLength(1 + 10);
  });

  it("opens a quote's breakdown from the list", async () => {
    renderApp("/ingresar");
    await signIn(ADMIN);
    const table = await screen.findByRole("table", { name: es.records.quotesCaption });

    const [first] = within(table).getAllByRole("button", { name: es.records.showDetail });
    fireEvent.click(first as HTMLElement);

    expect((await screen.findAllByRole("table", { name: es.quote.caption })).length).toBeGreaterThan(0);
  });

  it("ends the session and explains it when the server rejects the token", async () => {
    const future = Date.now() + 3_600_000;
    window.sessionStorage.setItem(
      "eventsound.session",
      JSON.stringify({ token: "stale.tok.en", role: "admin", expiresAt: future }),
    );

    renderApp("/admin/cotizaciones");

    expect(await heading(es.auth.title)).toBeInTheDocument();
    expect(await screen.findByText(es.auth.expiredTitle)).toBeInTheDocument();
    expect(window.sessionStorage.getItem("eventsound.session")).toBeNull();
  });
});
