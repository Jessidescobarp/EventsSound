import { describe, expect, it } from "vitest";
import { portfolioInput, type PortfolioDraft } from "./portfolioForm";

const DRAFT: PortfolioDraft = {
  title: " Boda en la finca ",
  kind: "Boda",
  description: "Sonido y luces.",
  equipment: "Sonido\n\n  Luces LED  \n",
  visible: true,
};

describe("portfolio form", () => {
  it("builds the API input: trimmed text, one equipment name per non-empty line", () => {
    expect(portfolioInput(DRAFT)).toEqual({
      ok: true,
      value: {
        title: "Boda en la finca",
        kind: "Boda",
        description: "Sonido y luces.",
        equipment: ["Sonido", "Luces LED"],
        visible: true,
      },
    });
  });

  it("accepts an event with no equipment", () => {
    expect(portfolioInput({ ...DRAFT, equipment: "" }).ok).toBe(true);
  });

  it.each([
    ["title", { title: "   " }],
    ["title", { title: "x".repeat(121) }],
    ["kind", { kind: "uno\ndos" }],
    ["description", { description: "x".repeat(501) }],
    ["equipment", { equipment: Array.from({ length: 13 }, (_, i) => `e${i}`).join("\n") }],
    ["equipment", { equipment: "x".repeat(81) }],
  ])("flags %s", (field, over) => {
    const result = portfolioInput({ ...DRAFT, ...over });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(Object.keys(result.errors)).toEqual([field]);
  });
});
