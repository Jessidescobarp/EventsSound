import { describe, expect, it } from "vitest";
import { parsePortfolio } from "./portfolio";

const EVENT = { id: 1, title: "Boda", kind: "Boda", description: "Texto", equipment: ["Sonido"], visible: true };

describe("parsePortfolio", () => {
  it("parses a list of events", () => {
    expect(parsePortfolio({ events: [EVENT] })).toEqual([EVENT]);
  });

  it.each([
    [{ events: "x" }],
    [{ events: [{ ...EVENT, id: 0 }] }],
    [{ events: [{ ...EVENT, title: "uno\ndos" }] }],
    [{ events: [{ ...EVENT, equipment: [1] }] }],
    [{ events: [{ ...EVENT, equipment: Array(13).fill("x") }] }],
    [{ events: [{ ...EVENT, visible: "yes" }] }],
  ])("rejects a malformed body: %#", (body) => {
    expect(() => parsePortfolio(body)).toThrow();
  });
});
