import { ApiError, apiFetch } from "./client";
import { obj } from "./parse";

/** Contract of POST/PUT /admin/catalog/items|packages (backend routes/admin_catalog.py). */
export interface ItemInput {
  code: string;
  name: string;
  category: string;
  stock_quantity: number;
  unit_price_cop: number;
}

export interface PackageInput {
  code: string;
  name: string;
  discount_bps: number;
  lines: { item_code: string; quantity: number }[];
}

export type SaveFailure =
  | "code_taken"
  | "not_found"
  | "unknown_item"
  | "invalid"
  | "unauthenticated"
  | "forbidden"
  | "unavailable"
  | "transient"
  | "unexpected"
  | "aborted";

function parseSaved(json: unknown): true {
  if (obj(json).status !== "saved") throw new Error("unexpected save response");
  return true;
}

/** Creates (POST, the code travels in the body) or edits (PUT, the code is in the path). */
function save(
  resource: "items" | "packages",
  creating: boolean,
  input: { code: string },
  token: string,
  signal?: AbortSignal,
): Promise<true> {
  const { code, ...fields } = input;
  return apiFetch(creating ? `/admin/catalog/${resource}` : `/admin/catalog/${resource}/${encodeURIComponent(code)}`, {
    method: creating ? "POST" : "PUT",
    jsonBody: creating ? input : fields,
    parse: parseSaved,
    token,
    signal,
  });
}

export const saveItem = (input: ItemInput, creating: boolean, token: string, signal?: AbortSignal) =>
  save("items", creating, input, token, signal);

export const savePackage = (input: PackageInput, creating: boolean, token: string, signal?: AbortSignal) =>
  save("packages", creating, input, token, signal);

export function classifySaveError(error: unknown): SaveFailure {
  if (!(error instanceof ApiError)) return "unexpected";
  const { code, status, detail } = error;
  if (code === "aborted") return "aborted";
  if (code === "not_found") return "not_found";
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 409 && detail === "code_taken") return "code_taken";
  if (status === 422) return detail === "unknown_item" ? "unknown_item" : "invalid";
  if (status === 503) return "unavailable";
  if (code === "network" || code === "timeout" || code === "server") return "transient";
  return "unexpected";
}
