import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { stepAfterFailure } from "../components/admin/ConfirmFlow";
import { es } from "../copy/es";
import { createFakeFetch, DEMO_PASSWORD, resetDemoCatalog } from "../mocks/fakeApi";
import { renderApp } from "../test/renderApp";

const t = es.agentAdmin;
const c = t.confirm;

beforeEach(() => {
  resetDemoCatalog();
  window.localStorage.clear();
  window.sessionStorage.setItem(
    "eventsound.session",
    JSON.stringify({ token: "demo.admin.token", role: "admin", expiresAt: Date.now() + 3_600_000 }),
  );
});

/** Fake API, except that PUT /apply answers `apply` when given. */
const withApply = (apply?: Response): typeof fetch => {
  const fake = createFakeFetch({ latencyMs: 0 });
  return (input, init) => (apply && String(input).endsWith("/apply") ? Promise.resolve(apply.clone()) : fake(input, init));
};
const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
const dialog = (name: string) => screen.findByRole("dialog", { name });
const button = (name: string) => screen.getByRole("button", { name });

/** Edits one field, opens modal 1 from the real trigger and moves on to modal 2. */
async function toConfirm(field: "tone" | "daily_token_cap" = "tone") {
  await screen.findByRole("form", { name: t.tab });
  if (field === "tone") fill(t.fields.tone!, "formal");
  else fill(t.fields.daily_token_cap!, "300000");
  const trigger = button(t.review);
  trigger.focus();
  fireEvent.click(trigger);
  await dialog(c.reviewTitle);
  fireEvent.click(button(c.continue));
  await dialog(c.confirmTitle);
  return trigger;
}
const type = (value: string) => fill(c.typeLabel("APLICAR"), value);

describe("double confirmation", () => {
  it("shows the impact in modal 1, then applies only after the exact word", async () => {
    renderApp("/admin/agente", withApply());
    await screen.findByRole("form", { name: t.tab });
    fill(t.fields.tone!, "formal");
    fireEvent.click(button(t.review));
    const first = await dialog(c.reviewTitle);
    expect(within(first).getByText(c.impact)).toBeInTheDocument();
    expect(within(first).getByText(`${t.diffTo}: ${t.tones.formal}`)).toBeInTheDocument();
    fireEvent.click(button(c.continue));

    await dialog(c.confirmTitle);
    for (const wrong of ["", "aplicar", "APLICAR ", "APLICA"]) {
      type(wrong);
      expect(button(c.apply)).toBeDisabled();
    }
    expect(screen.queryByLabelText(c.passwordLabel)).toBeNull(); // a tone change needs no password
    type("APLICAR");
    fireEvent.click(button(c.apply));

    expect(await screen.findByText(c.applied(1))).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(screen.getByLabelText(t.fields.tone!)).toHaveValue("formal"));
  });

  it("asks for the password only when the change needs it, and never keeps it", async () => {
    renderApp("/admin/agente", withApply());
    await toConfirm("daily_token_cap");
    const password = screen.getByLabelText(c.passwordLabel);
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    type("APLICAR");
    expect(button(c.apply)).toBeDisabled(); // password still empty

    fill(c.passwordLabel, "wrong-password");
    fireEvent.click(button(c.apply));
    expect(await screen.findByRole("alert")).toHaveTextContent(t.errors.reauth_failed!);
    expect(screen.getByRole("dialog", { name: c.confirmTitle })).toBeInTheDocument();
    expect(screen.getByLabelText(c.passwordLabel)).toHaveValue("");

    fill(c.passwordLabel, DEMO_PASSWORD);
    fireEvent.click(button(c.apply));
    expect(await screen.findByText(c.applied(1))).toBeInTheDocument();
    const stored = JSON.stringify([window.localStorage, window.sessionStorage, { ...window.localStorage }, { ...window.sessionStorage }]);
    expect(stored).not.toContain(DEMO_PASSWORD);
    expect(stored).not.toContain("demo-confirm");
    expect(window.localStorage).toHaveLength(0);
  });

  it.each([
    [403, { detail: "token_used" }, {}, t.errors.token_stale, c.reviewAgain],
    [403, { detail: "token_expired" }, {}, t.errors.token_stale, c.reviewAgain],
    [403, { detail: "token_mismatch" }, {}, t.errors.token_stale, c.reviewAgain],
    [403, { detail: "reauth_failed" }, {}, t.errors.reauth_failed, c.apply],
    [429, { detail: "rate_limited" }, { "Retry-After": "30" }, `${t.errors.rate_limited} ${t.retryIn(30)}`, c.apply],
    [503, { detail: "confirmation_unavailable" }, {}, t.errors.confirmation_unavailable, c.apply],
  ])("maps a %i %j answer to a step and a Spanish message", async (status, body, headers, text, expectedButton) => {
    renderApp("/admin/agente", withApply(Response.json(body, { status, headers })));
    await toConfirm();
    type("APLICAR");
    fireEvent.click(button(c.apply));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(text));
    expect(button(expectedButton)).toBeInTheDocument();
  });

  it("asks for a new preview after a spent token and then lets the admin continue", async () => {
    renderApp("/admin/agente", withApply(Response.json({ detail: "token_used" }, { status: 403 })));
    await toConfirm();
    type("APLICAR");
    fireEvent.click(button(c.apply));
    await dialog(c.reviewTitle);
    expect(screen.queryByRole("button", { name: c.continue })).toBeNull();

    fireEvent.click(await screen.findByRole("button", { name: c.reviewAgain }));
    expect(await screen.findByRole("button", { name: c.continue })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reloads and says someone else changed the configuration on a 409", async () => {
    renderApp("/admin/agente", withApply(Response.json({ detail: "version_conflict" }, { status: 409 })));
    await toConfirm();
    type("APLICAR");
    fireEvent.click(button(c.apply));
    expect(await screen.findByText(c.conflict)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([
    ["token_stale", "review"],
    ["version_conflict", "conflict"],
    ["reauth_failed", "confirm"],
    ["rate_limited", "confirm"],
    ["confirmation_unavailable", "confirm"],
    ["typed_confirmation", "confirm"],
  ] as const)("stepAfterFailure(%s) = %s", (kind, step) => {
    expect(stepAfterFailure(kind)).toBe(step);
  });
});

describe("dialog accessibility", () => {
  it("is modal, labelled, starts on the safe button and keeps Tab inside", async () => {
    renderApp("/admin/agente", withApply());
    await screen.findByRole("form", { name: t.tab });
    fill(t.fields.tone!, "formal");
    fireEvent.click(button(t.review));
    const modal = await dialog(c.reviewTitle);
    expect(modal).toHaveAttribute("aria-modal", "true");
    expect(button(c.cancel)).toHaveFocus();

    button(c.continue).focus();
    fireEvent.keyDown(modal, { key: "Tab" });
    expect(button(c.cancel)).toHaveFocus();
    fireEvent.keyDown(modal, { key: "Tab", shiftKey: true });
    expect(button(c.continue)).toHaveFocus();
  });

  it.each(["review", "confirm"] as const)("Escape closes the %s step and returns focus to the trigger", async (where) => {
    renderApp("/admin/agente", withApply());
    let trigger: HTMLElement;
    if (where === "confirm") trigger = await toConfirm();
    else {
      await screen.findByRole("form", { name: t.tab });
      fill(t.fields.tone!, "formal");
      trigger = button(t.review);
      trigger.focus();
      fireEvent.click(trigger);
      await dialog(c.reviewTitle);
    }
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("focuses the word field when modal 2 opens", async () => {
    renderApp("/admin/agente", withApply());
    await toConfirm();
    expect(screen.getByLabelText(c.typeLabel("APLICAR"))).toHaveFocus();
  });
});
