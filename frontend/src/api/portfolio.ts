import { apiFetch } from "./client";
import { bool, int, list, obj, str } from "./parse";

/** Contract of GET /portfolio and /admin/portfolio (backend routes/portfolio.py). */
export interface PortfolioEvent {
  id: number;
  title: string;
  kind: string;
  description: string;
  equipment: string[];
  visible: boolean;
}

export interface PortfolioInput {
  title: string;
  kind: string;
  description: string;
  equipment: string[];
  visible: boolean;
}

const MAX_EVENTS = 500;

function parseEvent(value: unknown): PortfolioEvent {
  const o = obj(value);
  return {
    id: int(o, "id", 1, Number.MAX_SAFE_INTEGER),
    title: str(o, "title", 120),
    kind: str(o, "kind", 40),
    description: str(o, "description", 500),
    equipment: list(o.equipment, 12, (name) => str({ name: name as unknown }, "name", 80)),
    visible: bool(o, "visible"),
  };
}

export function parsePortfolio(json: unknown): PortfolioEvent[] {
  return list(obj(json).events, MAX_EVENTS, parseEvent);
}

export function loadPortfolio(signal?: AbortSignal): Promise<PortfolioEvent[]> {
  return apiFetch("/portfolio", { parse: parsePortfolio, signal });
}

export function loadAllPortfolio(token: string, signal?: AbortSignal): Promise<PortfolioEvent[]> {
  return apiFetch("/admin/portfolio", { parse: parsePortfolio, token, signal });
}

function parseSaved(json: unknown): true {
  int(obj(json), "id", 1, Number.MAX_SAFE_INTEGER);
  return true;
}

/** Creates (`id` null, POST) or edits (PUT) one event; `visible: false` hides it. */
export function savePortfolioEvent(
  input: PortfolioInput,
  id: number | null,
  token: string,
  signal?: AbortSignal,
): Promise<true> {
  return apiFetch(id === null ? "/admin/portfolio" : `/admin/portfolio/${id}`, {
    method: id === null ? "POST" : "PUT",
    jsonBody: input,
    parse: parseSaved,
    token,
    signal,
  });
}
