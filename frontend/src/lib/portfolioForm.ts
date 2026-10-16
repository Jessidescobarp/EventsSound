import { hasForbiddenChars } from "../api/client";
import type { PortfolioInput } from "../api/portfolio";

/** The form holds raw strings; this checks them with the same bounds as the API. */
export interface PortfolioDraft {
  title: string;
  kind: string;
  description: string;
  /** One name per line. */
  equipment: string;
  visible: boolean;
}

export type PortfolioErrors = Partial<Record<"title" | "kind" | "description" | "equipment", true>>;

const MAX_EQUIPMENT = 12;
const MAX_EQUIPMENT_NAME = 80;

function fits(text: string, max: number): boolean {
  const trimmed = text.trim();
  return trimmed.length >= 1 && trimmed.length <= max && !hasForbiddenChars(trimmed);
}

export function portfolioInput(
  draft: PortfolioDraft,
): { ok: true; value: PortfolioInput } | { ok: false; errors: PortfolioErrors } {
  const errors: PortfolioErrors = {};
  if (!fits(draft.title, 120)) errors.title = true;
  if (!fits(draft.kind, 40)) errors.kind = true;
  if (!fits(draft.description, 500)) errors.description = true;
  const names = draft.equipment
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
  if (names.length > MAX_EQUIPMENT || names.some((name) => !fits(name, MAX_EQUIPMENT_NAME))) {
    errors.equipment = true;
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    value: {
      title: draft.title.trim(),
      kind: draft.kind.trim(),
      description: draft.description.trim(),
      equipment: names,
      visible: draft.visible,
    },
  };
}
