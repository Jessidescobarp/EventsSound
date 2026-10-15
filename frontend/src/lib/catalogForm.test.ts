import { describe, expect, it } from "vitest";
import { itemInput, packageInput, type ItemDraft, type PackageDraft } from "./catalogForm";

const ITEM: ItemDraft = { code: "sound_new", name: " Parlante ", category: "sound", stock: "4", price: "90000" };
const PACKAGE: PackageDraft = {
  code: "pkg_new",
  name: "Paquete",
  discount: "7.5",
  lines: [{ item_code: "sound_new", quantity: "2" }],
};

describe("item form", () => {
  it("turns a valid draft into the API input, trimming the name", () => {
    expect(itemInput(ITEM, true)).toEqual({
      ok: true,
      value: { code: "sound_new", name: "Parlante", category: "sound", stock_quantity: 4, unit_price_cop: 90000 },
    });
  });

  it("does not check the code when editing (it never changes)", () => {
    expect(itemInput({ ...ITEM, code: "" }, false).ok).toBe(true);
  });

  it.each([
    ["code", { code: "Bad Code" }],
    ["name", { name: "   " }],
    ["name", { name: "uno\ndos" }],
    ["name", { name: "x".repeat(121) }],
    ["category", { category: "pizza" }],
    ["stock", { stock: "-1" }],
    ["stock", { stock: "1.5" }],
    ["stock", { stock: "100001" }],
    ["price", { price: "" }],
    ["price", { price: "1000000001" }],
  ])("flags %s", (field, over) => {
    const result = itemInput({ ...ITEM, ...over }, true);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(Object.keys(result.errors)).toEqual([field]);
  });
});

describe("package form", () => {
  it("converts the percentage to basis points", () => {
    expect(packageInput(PACKAGE, true)).toEqual({
      ok: true,
      value: { code: "pkg_new", name: "Paquete", discount_bps: 750, lines: [{ item_code: "sound_new", quantity: 2 }] },
    });
  });

  it.each([
    ["discount", { discount: "100.5" }],
    ["discount", { discount: "1.234" }],
    ["discount", { discount: "-1" }],
    ["lines", { lines: [] }],
    ["lines", { lines: [PACKAGE.lines[0]!, PACKAGE.lines[0]!] }],
    ["lines", { lines: [{ item_code: "", quantity: "1" }] }],
    ["quantity", { lines: [{ item_code: "sound_new", quantity: "0" }] }],
  ])("flags %s", (field, over) => {
    const result = packageInput({ ...PACKAGE, ...over }, true);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(Object.keys(result.errors)).toEqual([field]);
  });
});
