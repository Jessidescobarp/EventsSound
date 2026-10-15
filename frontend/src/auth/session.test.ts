import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearSession, readSession, writeSession } from "./session";

const NOW = 1_800_000_000_000;
const session = { token: "aaa.bbb.ccc", role: "admin" as const, expiresAt: NOW + 60_000 };

describe("session storage", () => {
  beforeEach(() => window.sessionStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("round-trips a live session and forgets it on clear", () => {
    writeSession(session);
    expect(readSession(NOW)).toEqual(session);

    clearSession();
    expect(readSession(NOW)).toBeNull();
  });

  it.each([
    ["expired", JSON.stringify({ ...session, expiresAt: NOW - 1 })],
    ["not json", "{oops"],
    ["wrong role", JSON.stringify({ ...session, role: "owner" })],
    ["not a jwt", JSON.stringify({ ...session, token: "plain" })],
    ["no expiry", JSON.stringify({ token: session.token, role: "admin" })],
  ])("treats a %s entry as signed out and removes it", (_name, raw) => {
    window.sessionStorage.setItem("eventsound.session", raw);

    expect(readSession(NOW)).toBeNull();
    expect(window.sessionStorage.getItem("eventsound.session")).toBeNull();
  });

  it("never throws when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(readSession(NOW)).toBeNull();
    expect(() => writeSession(session)).not.toThrow();
    expect(() => clearSession()).not.toThrow();
  });
});
