import { describe, expect, it } from "vitest";
import { normalizeSpaces as norm } from "../test/text";
import { formatCop, formatPercentFromBps } from "./format";

describe("formatCop", () => {
  it.each([
    [0, "$ 0"],
    [25000, "$ 25.000"],
    [1234567, "$ 1.234.567"],
  ])("formats %i", (value, expected) => {
    expect(norm(formatCop(value))).toBe(expected);
  });
});

describe("formatPercentFromBps", () => {
  it.each([
    [1000, "10%"],
    [1050, "10,5%"],
    [1, "0,01%"],
    [10000, "100%"],
  ])("formats %i bps", (bps, expected) => {
    expect(norm(formatPercentFromBps(bps))).toBe(expected);
  });
});
