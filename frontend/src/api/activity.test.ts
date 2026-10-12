import { beforeEach, describe, expect, it, vi } from "vitest";
import { notifyApiSuccess, onApiSuccess } from "./activity";
import { apiFetch } from "./client";

describe("api activity bus", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example");
  });

  it("notifies subscribers until they unsubscribe", () => {
    const listener = vi.fn();
    const off = onApiSuccess(listener);
    notifyApiSuccess();
    expect(listener).toHaveBeenCalledTimes(1);
    off();
    notifyApiSuccess();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("apiFetch notifies after a valid response", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response('"ok"'))));
    const listener = vi.fn();
    const off = onApiSuccess(listener);
    await apiFetch("/x", { parse: (j) => j });
    off();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["404", () => Promise.resolve(new Response("{}", { status: 404 }))],
    ["503", () => Promise.resolve(new Response("{}", { status: 503 }))],
    ["network error", () => Promise.reject(new TypeError("x"))],
    ["a body that fails the guard", () => Promise.resolve(new Response('"ok"'))],
  ])("apiFetch does not notify on %s", async (name, impl) => {
    vi.stubGlobal("fetch", vi.fn(impl));
    const listener = vi.fn();
    const off = onApiSuccess(listener);
    await apiFetch("/x", {
      parse: (j) => {
        if (name.startsWith("a body")) throw new Error("bad");
        return j;
      },
    }).catch(() => undefined);
    off();
    expect(listener).not.toHaveBeenCalled();
  });
});
