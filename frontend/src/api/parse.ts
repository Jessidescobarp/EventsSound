import { hasForbiddenChars, replaceForbiddenChars } from "./client";

/** Shared runtime guards: every JSON the API returns is untrusted until it passes through these. */
export const MAX_TEXT = 120;

/** Splits on line breaks and tabs, which the reply may keep (captured, so odd indexes). */
const LAYOUT_SPLIT = /([\n\r\t])/;

export type Obj = Record<string, unknown>;

export function obj(value: unknown): Obj {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("object expected");
  return value as Obj;
}

/**
 * Text field. Short fields with control or bidi characters are rejected. With `multiline`
 * (the free-text reply) line breaks and tabs stay and the other forbidden characters become
 * spaces instead: the backend lets them through and the reply is shown as plain text anyway.
 */
export function str(o: Obj, key: string, max = MAX_TEXT, multiline = false): string {
  const v = o[key];
  if (typeof v !== "string" || v.length > max) throw new Error(key + ": invalid text");
  const text = multiline ? v.split(LAYOUT_SPLIT).map((p, i) => (i % 2 ? p : replaceForbiddenChars(p))).join("") : v;
  if (text.trim().length === 0 || (!multiline && hasForbiddenChars(text))) throw new Error(key + ": invalid text");
  return text;
}

export function int(o: Obj, key: string, min: number, max: number): number {
  const v = o[key];
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < min || v > max) throw new Error(`${key}: invalid integer`);
  return v;
}

export function nullable<T>(value: unknown, read: (v: unknown) => T): T | null {
  return value === null ? null : read(value);
}

export function list<T>(value: unknown, max: number, read: (v: unknown) => T): T[] {
  if (!Array.isArray(value) || value.length > max) throw new Error("array expected");
  return value.map(read);
}


export function bool(o: Obj, key: string): boolean {
  const v = o[key];
  if (typeof v !== "boolean") throw new Error(`${key}: boolean expected`);
  return v;
}
