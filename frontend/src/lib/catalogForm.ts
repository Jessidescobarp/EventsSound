import { hasForbiddenChars } from "../api/client";
import type { ItemInput, PackageInput } from "../api/adminCatalog";

/** The forms hold raw strings; these functions check them with the same bounds as the API. */
export const CATEGORIES = ["sound", "lighting", "dj", "stage", "effects", "video", "staff"] as const;

const CODE = /^[a-z0-9_]{3,64}$/;
const MAX_NAME = 120;
const MAX_STOCK = 100_000;
const MAX_PRICE = 1_000_000_000;
const MAX_LINES = 30;
const MAX_QUANTITY = 1_000;

export interface ItemDraft {
  code: string;
  name: string;
  category: string;
  stock: string;
  price: string;
}

export interface LineDraft {
  item_code: string;
  quantity: string;
}

export interface PackageDraft {
  code: string;
  name: string;
  /** Percentage as typed, e.g. "7.5". */
  discount: string;
  lines: LineDraft[];
}

export type Checked<T, K extends string> = { ok: true; value: T } | { ok: false; errors: Partial<Record<K, true>> };

/** A non-negative whole number within `max`, or null. */
function whole(text: string, max: number, min = 0): number | null {
  const trimmed = text.trim();
  if (!/^\d{1,12}$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value >= min && value <= max ? value : null;
}

function validName(name: string): boolean {
  const trimmed = name.trim();
  return trimmed.length >= 1 && trimmed.length <= MAX_NAME && !hasForbiddenChars(trimmed);
}

export function itemInput(draft: ItemDraft, creating: boolean): Checked<ItemInput, keyof ItemDraft> {
  const errors: Partial<Record<keyof ItemDraft, true>> = {};
  if (creating && !CODE.test(draft.code)) errors.code = true;
  if (!validName(draft.name)) errors.name = true;
  if (!(CATEGORIES as readonly string[]).includes(draft.category)) errors.category = true;
  const stock = whole(draft.stock, MAX_STOCK);
  const price = whole(draft.price, MAX_PRICE);
  if (stock === null) errors.stock = true;
  if (price === null) errors.price = true;
  if (Object.keys(errors).length > 0 || stock === null || price === null) return { ok: false, errors };
  return {
    ok: true,
    value: {
      code: draft.code,
      name: draft.name.trim(),
      category: draft.category,
      stock_quantity: stock,
      unit_price_cop: price,
    },
  };
}

/** Percentage text to basis points ("7.5" -> 750), or null when it is not 0..100 with 2 decimals. */
function basisPoints(text: string): number | null {
  const match = /^(\d{1,3})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  const bps = Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return bps <= 10_000 ? bps : null;
}

export function packageInput(
  draft: PackageDraft,
  creating: boolean,
): Checked<PackageInput, "code" | "name" | "discount" | "lines" | "quantity"> {
  const errors: Partial<Record<"code" | "name" | "discount" | "lines" | "quantity", true>> = {};
  if (creating && !CODE.test(draft.code)) errors.code = true;
  if (!validName(draft.name)) errors.name = true;
  const bps = basisPoints(draft.discount);
  if (bps === null) errors.discount = true;
  const codes = draft.lines.map((line) => line.item_code);
  if (
    draft.lines.length < 1 ||
    draft.lines.length > MAX_LINES ||
    codes.some((code) => code === "") ||
    new Set(codes).size !== codes.length
  ) {
    errors.lines = true;
  }
  const quantities = draft.lines.map((line) => whole(line.quantity, MAX_QUANTITY, 1));
  if (quantities.some((quantity) => quantity === null)) errors.quantity = true;
  if (Object.keys(errors).length > 0 || bps === null) return { ok: false, errors };
  return {
    ok: true,
    value: {
      code: draft.code,
      name: draft.name.trim(),
      discount_bps: bps,
      lines: draft.lines.map((line, index) => ({ item_code: line.item_code, quantity: quantities[index] as number })),
    },
  };
}
