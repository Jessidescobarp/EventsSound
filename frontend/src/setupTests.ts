import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, vi, type MockInstance } from "vitest";

// Any console.error/warn (React act() warnings, failed prop types, unhandled app errors)
// fails the test. A test that expects one calls spy.mockClear() after asserting it.
let consoleSpies: MockInstance[] = [];

beforeEach(() => {
  consoleSpies = [vi.spyOn(console, "error"), vi.spyOn(console, "warn")];
  // jsdom logs "not implemented" for scrollTo; tests assert on this stub instead.
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  const calls = consoleSpies.flatMap((spy) => spy.mock.calls);
  expect(calls, "unexpected console.error / console.warn").toEqual([]);
});
