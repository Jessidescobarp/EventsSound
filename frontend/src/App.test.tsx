import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { es } from "./copy/es";
import { renderApp } from "./test/renderApp";

const ROUTES = [
  ["/", es.home.heroTitle],
  ["/quienes-somos", es.about.title],
  ["/portafolio", es.portfolio.title],
  ["/servicios", es.services.title],
  ["/cotizar", es.chat.title],
  ["/ruta-que-no-existe", es.notFound.title],
] as const;

describe("routing", () => {
  it.each(ROUTES)("route %s shows its h1", async (path, heading) => {
    renderApp(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it.each(ROUTES)("route %s has exactly one h1", async (path) => {
    renderApp(path);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("updates the document title per page", async () => {
    renderApp("/quienes-somos");
    await waitFor(() => expect(document.title).toBe(`${es.titles.about} · ${es.brand.name}`));
  });
});

describe("layout", () => {
  it("exposes the landmarks", () => {
    renderApp("/");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: es.a11y.mainNav })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("has a skip link as the first link, pointing at the focusable main", () => {
    renderApp("/");
    const [first] = screen.getAllByRole("link");
    expect(first).toHaveAccessibleName(es.a11y.skipLink);
    expect(first).toHaveAttribute("href", "#contenido");
    expect(screen.getByRole("main")).toHaveAttribute("id", "contenido");
    expect(screen.getByRole("main")).toHaveAttribute("tabindex", "-1");
  });

  it("links every section from the main navigation", () => {
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: es.a11y.mainNav });
    const hrefs = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/quienes-somos", "/portafolio", "/servicios", "/cotizar", "/ingresar"]);
  });

  it("marks only the current page with aria-current", () => {
    renderApp("/portafolio");
    const nav = screen.getByRole("navigation", { name: es.a11y.mainNav });
    const current = Array.from(nav.querySelectorAll("a[aria-current='page']"));
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent(es.nav.portfolio);
  });

  it("navigates on click, updates the heading and moves focus to main", async () => {
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: es.a11y.mainNav });
    expect(screen.getByRole("main")).not.toHaveFocus();
    fireEvent.click(Array.from(nav.querySelectorAll("a"))[1]!);
    expect(
      await screen.findByRole("heading", { level: 1, name: es.about.title }),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
  });

  it("serves a Spanish document", () => {
    // jsdom does not load index.html, so assert the served document directly.
    const html = new DOMParser().parseFromString(
      readFileSync(resolve(import.meta.dirname, "../index.html"), "utf8"),
      "text/html",
    );
    expect(html.documentElement.lang).toBe("es");
    expect(html.title).toBe("EventSoundDR");
    expect(html.querySelector("#root")).not.toBeNull();
  });

  it("never renders raw HTML from copy or data (no script or inline handler nodes)", async () => {
    const { container } = renderApp("/portafolio");
    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("[onerror], [onclick]")).toBeNull();
  });
});

describe("images", () => {
  it("every image has an accessible name", async () => {
    renderApp("/portafolio");
    await screen.findByRole("heading", { level: 1 });
    const images = screen.getAllByRole("img");
    expect(images.length).toBeGreaterThan(0);
    for (const image of images) expect(image).toHaveAccessibleName();
  });
});

describe("pages", () => {
  it("home links to the catalog and to the chat", () => {
    renderApp("/");
    const main = screen.getByRole("main");
    const links = Array.from(main.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(links).toContain("/servicios");
    expect(links).toContain("/cotizar");
    for (const link of screen.getAllByRole("link", { name: es.home.ctaServices })) {
      expect(link).toHaveAttribute("href", "/servicios");
    }
  });

  it("about lists the values", () => {
    renderApp("/quienes-somos");
    for (const value of es.about.values) {
      expect(screen.getByRole("heading", { level: 3, name: value.title })).toBeInTheDocument();
    }
  });

  it("portfolio shows every event with its image", () => {
    renderApp("/portafolio");
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(es.portfolio.events.length);
    for (const event of es.portfolio.events) {
      expect(screen.getByRole("img", { name: es.portfolio.imageLabel(event.title) })).toBeInTheDocument();
    }
  });

  it("chat page offers a labelled message box and a send button", () => {
    renderApp("/cotizar");
    expect(screen.getByRole("textbox", { name: es.chat.inputLabel })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: es.chat.send })).toBeInTheDocument();
  });

  it("not found offers a way home", () => {
    renderApp("/no-existe");
    expect(screen.getByRole("link", { name: es.notFound.cta })).toHaveAttribute("href", "/");
  });
});

it("does not call a missing API during static pages when health is down", async () => {
  const down = vi.fn(() => Promise.reject(new TypeError("down")));
  renderApp("/quienes-somos", down as unknown as typeof fetch);
  expect(await screen.findByRole("heading", { level: 1, name: es.about.title })).toBeInTheDocument();
});
