import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { classifySaveError, saveItem, savePackage } from "./adminCatalog";
import { ApiError } from "./client";

const ITEM = { code: "sound_new", name: "Parlante", category: "sound", stock_quantity: 3, unit_price_cop: 90000 };
const PACKAGE = { code: "pkg_new", name: "Paquete", discount_bps: 500, lines: [{ item_code: "sound_new", quantity: 2 }] };

function stubFetch(status = 201, body: unknown = { status: "saved" }) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("saving catalog entries", () => {
  beforeEach(() => vi.stubEnv("VITE_API_BASE_URL", "https://api.example"));
  afterEach(() => vi.unstubAllGlobals());

  it("creates with POST and the code in the body, sending the bearer token", async () => {
    const fetchMock = stubFetch();

    await saveItem(ITEM, true, "t.o.k");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example/admin/catalog/items");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(ITEM);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer t.o.k");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  });

  it("edits with PUT, the code in the path and not in the body", async () => {
    const fetchMock = stubFetch(200);

    await savePackage(PACKAGE, false, "t.o.k");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example/admin/catalog/packages/pkg_new");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).not.toHaveProperty("code");
  });

  it("rejects a response that is not the saved acknowledgement", async () => {
    stubFetch(200, { status: "nope" });

    await expect(saveItem(ITEM, false, "t.o.k")).rejects.toMatchObject({ code: "invalid_response" });
  });
});

describe("classifySaveError", () => {
  const http = (status: number, detail?: string) => new ApiError("http", "x", status, { detail });

  it.each([
    [http(401), "unauthenticated"],
    [http(403), "forbidden"],
    [http(409, "code_taken"), "code_taken"],
    [new ApiError("not_found", "x", 404), "not_found"],
    [http(422, "unknown_item"), "unknown_item"],
    [http(422, "invalid_catalog_entry"), "invalid"],
    [new ApiError("server", "x", 503, { detail: "storage_unavailable" }), "unavailable"],
    [new ApiError("server", "x", 500), "transient"],
    [new ApiError("network", "x"), "transient"],
    [new ApiError("aborted", "x"), "aborted"],
    [new Error("boom"), "unexpected"],
  ])("maps %# to %s", (error, expected) => {
    expect(classifySaveError(error)).toBe(expected);
  });
});
