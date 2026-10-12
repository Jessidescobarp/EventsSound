const NBSP = String.fromCharCode(160);

/** Intl output uses non-breaking spaces; tests compare with plain spaces. */
export function normalizeSpaces(value: string | null): string {
  return (value ?? "").replaceAll(NBSP, " ");
}
