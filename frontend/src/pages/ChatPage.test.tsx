import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VIEW_ALL_OPTION, type ChatResponse } from "../api/chat";
import { es } from "../copy/es";
import { renderApp } from "../test/renderApp";
import { normalizeSpaces } from "../test/text";
import { advanceInSteps } from "../test/timers";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

const answer = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  request_id: "r1", status: "refused", reply: "Hola, cuéntame de tu evento.", quote: null,
  availability: null, missing_fields: [], reply_source: "static", options: [], ...over,
});

const quoteAnswer = answer({
  status: "quote",
  reply: "Total: $1 COP (prose is never parsed)",
  reply_source: "llm",
  quote: {
    version: 1, currency: "COP", rental_days: 1, subtotal: 460_000, total: 460_000,
    lines: [
      { kind: "item", code: "spk", label: "Parlante activo", quantity: 2, periods: 1, unit_amount: 230_000, rate_bps: null, basis: null, amount: 460_000 },
    ],
  },
  availability: { is_available: false, shortages: [{ item_code: "spk", requested: 2, available: 1 }] },
});

type Chat = (init: RequestInit | undefined) => Response | Promise<Response>;
/** /health is always ok; POST /quote/chat goes to `chat`. Returns the recorded chat bodies. */
function setup(chat: Chat) {
  const bodies: Array<{ messages: Array<{ role: string; content: string }> }> = [];
  const impl = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    if (new URL(String(input)).pathname === "/health") return Promise.resolve(json({ status: "ok" }));
    bodies.push(JSON.parse(String(init?.body)));
    return Promise.resolve(chat(init));
  };
  renderApp("/cotizar", impl);
  return bodies;
}

const input = () => screen.getByRole("textbox", { name: es.chat.inputLabel });
const send = (text: string) => {
  fireEvent.change(input(), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: es.chat.send }));
};
const log = () => screen.getByRole("log");

afterEach(() => vi.useRealTimers());

describe("chat page", () => {
  it("renders an accessible, empty conversation", () => {
    setup(() => json(answer()));
    expect(screen.getByRole("heading", { level: 1, name: es.chat.title })).toBeInTheDocument();
    expect(log()).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("button", { name: es.chat.newConversation })).toBeDisabled();
    expect(screen.queryByText(es.chat.demoHint)).toBeNull();
  });

  it("sends the history, shows the structured breakdown and returns focus to the input", async () => {
    const bodies = setup(() => json(quoteAnswer));
    send("  Necesito sonido  ");
    expect(await within(log()).findByRole("table", { name: es.quote.caption })).toBeInTheDocument();
    expect(bodies[0]).toEqual({ messages: [{ role: "user", content: "Necesito sonido" }] });
    expect(input()).toHaveValue("");
    expect(input()).toHaveFocus();
    const table = within(log()).getByRole("table");
    expect(normalizeSpaces(within(table).getByText(es.quote.total).closest("tr")!.textContent)).toContain("$ 460.000");
    expect(within(table).getByText("Parlante activo")).toBeInTheDocument();
    expect(within(log()).getByText(es.chat.source.llm)).toBeInTheDocument();
    expect(within(log()).getByText(es.quote.shortage(2, 1), { exact: false })).toBeInTheDocument();

    send("Gracias");
    await screen.findAllByText(es.chat.source.llm);
    expect(bodies[1]?.messages.map((m) => m.role)).toEqual(["user", "assistant", "user"]);
  });

  it("lists what is missing on a clarification", async () => {
    setup(() => json(answer({ status: "clarification", missing_fields: ["guest_count", "made_up_field"] })));
    send("Hola");
    expect(await screen.findByText(es.quote.missing.guest_count)).toBeInTheDocument();
    expect(within(log()).getAllByRole("listitem").some((li) => li.textContent === "made_up_field")).toBe(false);
  });

  it("offers options under the latest answer only and sends the clicked one as a message", async () => {
    const asks = answer({ status: "clarification", options: ["Paquete DJ", "<b>Ver todo el catalogo</b>"] });
    const bodies = setup((init) => (JSON.parse(String(init?.body)).messages.length === 1 ? json(asks) : json(answer())));
    send("Quiero parlantes");
    const group = await screen.findByRole("group", { name: es.chat.optionsLabel });
    expect(within(group).getAllByRole("button")).toHaveLength(2);
    expect(group.querySelector("b")).toBeNull(); // plain text, never markup
    fireEvent.click(within(group).getByRole("button", { name: "Paquete DJ" }));
    expect(bodies[1]?.messages.at(-1)).toEqual({ role: "user", content: "Paquete DJ" });
    expect(await within(log()).findAllByRole("listitem")).toHaveLength(4);
    expect(screen.queryByRole("group", { name: es.chat.optionsLabel })).toBeNull();
  });

  it("renders the view-all option as a link to the catalog and does not send it", async () => {
    const bodies = setup(() => json(answer({ status: "clarification", options: ["Paquete DJ", VIEW_ALL_OPTION] })));
    send("Hola");
    const link = await screen.findByRole("link", { name: VIEW_ALL_OPTION });
    expect(link).toHaveAttribute("href", "/servicios");
    expect(screen.getByRole("button", { name: "Paquete DJ" })).toBeInTheDocument();
    fireEvent.click(link);
    expect(bodies).toHaveLength(1);
  });

  it("hides the options while a request is in flight", async () => {
    let finish: (r: Response) => void = () => {};
    let calls = 0;
    setup(() => (++calls === 1 ? json(answer({ status: "clarification", options: ["Paquete DJ"] })) : new Promise<Response>((resolve) => (finish = resolve))));
    send("Hola");
    fireEvent.click(await screen.findByRole("button", { name: "Paquete DJ" }));
    expect(await screen.findByText(es.chat.typing)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Paquete DJ" })).toBeNull();
    await act(async () => finish(json(answer())));
  });

  it("renders model text as inert text: no markup, no links", async () => {
    const evil = '<img src=x onerror="alert(1)"> javascript:alert(1) [click](javascript:alert(1)) <a href="https://evil.example">x</a>';
    setup(() => json(answer({ reply: evil })));
    send("Hola");
    expect(await within(log()).findByText(evil)).toBeInTheDocument();
    expect(log().querySelector("img, a, script")).toBeNull();
  });

  it("ignores a second send while one is in flight", async () => {
    let finish: (r: Response) => void = () => {};
    const bodies = setup(() => new Promise<Response>((resolve) => (finish = resolve)));
    send("Uno");
    expect(await screen.findByText(es.chat.typing)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: es.chat.send })).toBeDisabled();
    fireEvent.change(input(), { target: { value: "Dos" } });
    fireEvent.submit(input().closest("form")!);
    expect(bodies).toHaveLength(1);
    await act(async () => finish(json(answer())));
    expect(await within(log()).findByText(answer().reply)).toBeInTheDocument();
  });

  it("aborts the request and drops its answer after a new conversation", async () => {
    let signal: AbortSignal | null | undefined;
    let finish: (r: Response) => void = () => {};
    setup((init) => {
      signal = init?.signal;
      return new Promise<Response>((resolve) => (finish = resolve)) as unknown as Response;
    });
    send("Uno");
    await screen.findByText(es.chat.typing);
    fireEvent.click(screen.getByRole("button", { name: es.chat.newConversation }));
    expect(signal?.aborted).toBe(true);
    await act(async () => finish(json(answer({ reply: "respuesta vieja" }))));
    expect(screen.queryByText("respuesta vieja")).toBeNull();
    expect(screen.queryByText(es.chat.typing)).toBeNull();
  });

  it("aborts the request when the page unmounts", async () => {
    let signal: AbortSignal | null | undefined;
    const bodies = setup((init) => {
      signal = init?.signal;
      return new Promise<Response>(() => {}) as unknown as Response;
    });
    send("Uno");
    await screen.findByText(es.chat.typing);
    fireEvent.click(screen.getByRole("link", { name: es.nav.services }));
    expect(signal?.aborted).toBe(true);
    expect(bodies).toHaveLength(1);
  });

  it("refuses an empty or too long draft without calling the API", () => {
    const bodies = setup(() => json(answer()));
    send("   ");
    expect(screen.getByRole("alert")).toHaveTextContent(es.chat.errors.empty.title);
    send("\u200b\u2060\ufeff");
    expect(screen.getByRole("alert")).toHaveTextContent(es.chat.errors.empty.title);
    send("x".repeat(1001));
    expect(screen.getByRole("alert")).toHaveTextContent(es.chat.errors.too_long.title);
    send("\u2026".repeat(400)); // NFKC expands it to 1200 characters
    expect(screen.getByRole("alert")).toHaveTextContent(es.chat.errors.too_long.title);
    expect(bodies).toHaveLength(0);
  });

  it("names a package by its own line, not by the discount that shares its code", async () => {
    const line = (kind: string, label: string | null, amount: number) => ({
      kind, code: "pkg_a", label, quantity: 1, periods: 1, unit_amount: kind === "package" ? 1000 : null, rate_bps: null, basis: null, amount,
    });
    setup(() =>
      json({
        ...quoteAnswer,
        quote: { ...quoteAnswer.quote, lines: [line("package", "Paquete Fiesta", 1000), line("package_discount", "Descuento", -100)], subtotal: 900, total: 900 },
        availability: { is_available: false, shortages: [{ item_code: "pkg_a", requested: 1, available: 0 }, { item_code: "Weird Code!", requested: 1, available: 0 }] },
      }),
    );
    send("Hola");
    const list = (await within(log()).findByText(es.quote.availabilityTitle)).parentElement!;
    expect(within(list).getByText(/Paquete Fiesta/)).toBeInTheDocument();
    expect(list).not.toHaveTextContent("Weird Code!");
    expect(list).toHaveTextContent(es.quote.equipmentFallback);
  });
});

describe("chat errors", () => {
  it.each([
    ["kill switch", 503, { detail: "chat_disabled", message: "El asistente de cotizaciones no esta disponible por ahora." }, es.chat.errors.disabled.title],
    ["daily budget", 503, { detail: "daily_budget_exhausted", message: "Limite diario." }, es.chat.errors.budget.title],
    ["too large", 413, { detail: "payload_too_large", message: "El mensaje es demasiado grande." }, es.chat.errors.invalid.title],
    ["invalid", 422, { detail: "invalid_request", message: "No valida.", errors: [] }, es.chat.errors.invalid.title],
    ["provider down", 503, { detail: "llm_unavailable", message: "x" }, es.chat.errors.transient.title],
    ["unexpected failure", 500, { detail: "internal_error", message: "x" }, es.chat.errors.transient.title],
    ["a body that is not the contract", 200, { reply: "sin forma" }, es.chat.errors.unexpected.title],
  ])("%s shows a Spanish alert", async (_name, status, body, title) => {
    setup(() => json(body, status));
    send("Hola");
    expect(await screen.findByRole("alert")).toHaveTextContent(title);
  });

  it("does not offer a retry when the assistant is disabled", async () => {
    const bodies = setup(() => json({ detail: "chat_disabled", message: "x" }, 503));
    send("Hola");
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: es.common.retry })).toBeNull();
    expect(screen.getByRole("link", { name: es.chat.catalogLink })).toHaveAttribute("href", "/servicios");
    expect(bodies).toHaveLength(1);
  });

  it("blocks sending during the Retry-After countdown and unblocks afterwards", async () => {
    vi.useFakeTimers();
    setup(() => json({ detail: "rate_limited", message: "Demasiadas." }, 429, { "Retry-After": "3" }));
    send("Hola");
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByRole("alert")).toHaveTextContent(es.chat.cooldown(3));
    expect(screen.getByRole("button", { name: es.chat.send })).toBeDisabled();
    await advanceInSteps(3_500);
    expect(screen.getByRole("button", { name: es.chat.send })).toBeEnabled();
  });

  it("takes a rejected turn out of the thread and restores the draft", async () => {
    let calls = 0;
    const bodies = setup(() => {
      calls += 1;
      return calls === 1 ? json({ detail: "invalid_request", message: "No valida.", errors: [] }, 422) : json(answer());
    });
    send("Mensaje rechazado");
    expect(await screen.findByRole("alert")).toHaveTextContent(es.chat.errors.invalid.title);
    expect(input()).toHaveValue("Mensaje rechazado");
    expect(within(log()).queryByText("Mensaje rechazado")).toBeNull();
    send("Otro mensaje");
    await within(log()).findByText(answer().reply);
    expect(bodies[1]?.messages).toEqual([{ role: "user", content: "Otro mensaje" }]);
  });

  it("falls back to a 10 s cooldown when a 429 has no Retry-After", async () => {
    vi.useFakeTimers();
    setup(() => json({ detail: "rate_limited", message: "Demasiadas." }, 429));
    send("Hola");
    await act(() => vi.advanceTimersByTimeAsync(0));
    await advanceInSteps(9_000, 1_000);
    expect(screen.getByRole("button", { name: es.chat.send })).toBeDisabled();
    await advanceInSteps(1_500, 500);
    expect(screen.getByRole("button", { name: es.chat.send })).toBeEnabled();
  });

  it("retries the same thread after a network failure", async () => {
    let calls = 0;
    const bodies = setup(() => {
      calls += 1;
      if (calls === 1) throw new TypeError("offline");
      return json(answer());
    });
    send("Hola");
    fireEvent.click(await screen.findByRole("button", { name: es.common.retry }));
    expect(await within(log()).findByText(answer().reply)).toBeInTheDocument();
    expect(bodies.map((b) => b.messages.length)).toEqual([1, 1]);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
