import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter, useNavigate } from "react-router";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { es } from "./copy/es";
import { createFakeFetch } from "./mocks/fakeApi";
import { renderApp } from "./test/renderApp";

const robots = () => document.head.querySelectorAll('meta[name="robots"]');
const mainLinks = () =>
  Array.from(
    screen.getByRole("navigation", { name: es.a11y.mainNav }).querySelectorAll("a"),
  );

describe("focus management", () => {
  it("does not move focus on the initial load", () => {
    renderApp("/portafolio");
    expect(screen.getByRole("main")).not.toHaveFocus();
    expect(document.body).toHaveFocus();
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("does not move focus on the initial load under StrictMode (effects run twice)", () => {
    renderApp("/portafolio", undefined, StrictMode);
    expect(screen.getByRole("main")).not.toHaveFocus();
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("on a link navigation focuses main without scrolling it into view, then scrolls to top", async () => {
    renderApp("/");
    const main = screen.getByRole("main");
    const focus = vi.spyOn(main, "focus");
    fireEvent.click(mainLinks()[1]!);
    await waitFor(() => expect(main).toHaveFocus());
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("does nothing when the link points at the page you are already on", async () => {
    renderApp("/portafolio");
    const main = screen.getByRole("main");
    const focus = vi.spyOn(main, "focus");
    const current = mainLinks().find((a) => a.getAttribute("aria-current") === "page")!;
    fireEvent.click(current);
    await Promise.resolve();
    expect(focus).not.toHaveBeenCalled();
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("does the same under StrictMode, once per navigation", async () => {
    renderApp("/", undefined, StrictMode);
    const main = screen.getByRole("main");
    const focus = vi.spyOn(main, "focus");
    fireEvent.click(mainLinks()[2]!);
    await waitFor(() => expect(main).toHaveFocus());
    expect(focus).toHaveBeenCalledTimes(1);
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("does not steal focus or scroll on Back/Forward (history POP)", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
    vi.stubGlobal("fetch", vi.fn(createFakeFetch({ latencyMs: 0 })));
    function Back() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => void navigate(-1)}>
          volver
        </button>
      );
    }
    render(
      <MemoryRouter initialEntries={["/", "/quienes-somos"]} initialIndex={1}>
        <App />
        <Back />
      </MemoryRouter>,
    );
    const main = screen.getByRole("main");
    fireEvent.click(screen.getByRole("button", { name: "volver" }));
    expect(await screen.findByRole("heading", { level: 1, name: es.home.heroTitle })).toBeInTheDocument();
    await Promise.resolve();
    expect(main).not.toHaveFocus();
    expect(window.scrollTo).not.toHaveBeenCalled();
  });
});

describe("noindex on the 404 page", () => {
  it("adds <meta name=robots content=noindex> on unknown routes", () => {
    renderApp("/no-existe");
    const tags = robots();
    expect(tags).toHaveLength(1);
    expect(tags[0]).toHaveAttribute("content", "noindex");
  });

  it("adds exactly one tag under StrictMode", () => {
    renderApp("/no-existe", undefined, StrictMode);
    expect(robots()).toHaveLength(1);
  });

  it("is absent on real pages and removed when leaving the 404", async () => {
    renderApp("/");
    expect(robots()).toHaveLength(0);
    const { unmount } = renderApp("/no-existe");
    expect(robots()).toHaveLength(1);
    unmount();
    expect(robots()).toHaveLength(0);
  });

  it("is removed after navigating from the 404 to a real page", async () => {
    renderApp("/no-existe");
    expect(robots()).toHaveLength(1);
    fireEvent.click(screen.getByRole("link", { name: es.notFound.cta }));
    await screen.findByRole("heading", { level: 1, name: es.home.heroTitle });
    expect(robots()).toHaveLength(0);
  });
});

describe("StrictMode render", () => {
  it.each(["/", "/quienes-somos", "/portafolio", "/servicios", "/cotizar", "/nada"])(
    "renders %s once, with one h1, landmarks and no console noise",
    async (path) => {
      renderApp(path, undefined, StrictMode);
      expect(await screen.findAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(screen.getAllByRole("main")).toHaveLength(1);
      expect(screen.getAllByRole("banner")).toHaveLength(1);
      expect(screen.getAllByRole("contentinfo")).toHaveLength(1);
    },
  );
});

describe("focus ring contrast (WCAG 2.2 non-text contrast, 3:1)", () => {
  const css = (name: string) => readFileSync(resolve(import.meta.dirname, "styles", name), "utf8");
  const token = (name: string) => {
    const line = css("tokens.css")
      .split("\n")
      .find((l) => l.trim().startsWith(`--color-${name}:`));
    const match = /(#[0-9a-fA-F]{6})/.exec(line ?? "");
    if (!match?.[1]) throw new Error(`token ${name} not found`);
    return match[1];
  };
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  };
  const ratio = (a: string, b: string) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi! + 0.05) / (lo! + 0.05);
  };

  it("uses a two-tone ring: a surface-coloured gap plus an ink outline", () => {
    const rule = /:focus-visible\s*\{([^}]*)\}/.exec(css("index.css"))?.[1] ?? "";
    expect(rule).toContain("outline: 3px solid var(--color-ink)");
    expect(rule).toContain("box-shadow: 0 0 0 5px var(--color-surface)");
  });

  it.each(["brand-900", "brand-700", "brand-600", "brand-500"])(
    "the surface-coloured ring separates from the hero gradient stop %s by >= 3:1",
    (stop) => {
      expect(ratio(token("surface"), token(stop))).toBeGreaterThanOrEqual(3);
    },
  );

  it.each(["surface", "surface-alt", "brand-50", "brand-100"])(
    "the ink outline separates from the light background %s by >= 3:1",
    (bg) => {
      expect(ratio(token("ink"), token(bg))).toBeGreaterThanOrEqual(3);
    },
  );
});
