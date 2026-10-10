import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the heading and a Spanish document", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "EventsSound" }),
    ).toBeInTheDocument();
    // jsdom does not load index.html, so assert the served document directly.
    const html = new DOMParser().parseFromString(
      readFileSync("index.html", "utf8"),
      "text/html",
    );
    expect(html.documentElement.lang).toBe("es");
  });
});
