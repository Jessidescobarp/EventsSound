import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { assertNoMocksInProduction, findMockMarkers, MOCK_MARKERS } from "./guards.mjs";

describe("assertNoMocksInProduction", () => {
  it("throws for a production build with VITE_USE_MOCKS=true", () => {
    expect(() => assertNoMocksInProduction("production", { VITE_USE_MOCKS: "true" })).toThrow(
      /VITE_USE_MOCKS/,
    );
  });

  it.each([
    ["development", { VITE_USE_MOCKS: "true" }],
    ["test", { VITE_USE_MOCKS: "true" }],
    ["production", {}],
    ["production", { VITE_USE_MOCKS: "false" }],
    ["production", { VITE_USE_MOCKS: "" }],
    ["production", { VITE_USE_MOCKS: "1" }],
  ])("allows mode %s with %j", (mode, env) => {
    expect(() => assertNoMocksInProduction(mode, env)).not.toThrow();
  });
});

describe("findMockMarkers and the CI check script", () => {
  let dir: string;
  const cli = join(import.meta.dirname, "check-no-mocks.mjs");

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "dist-check-"));
    mkdirSync(join(dir, "assets"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("uses a distinctive fake-catalog marker", () => {
    expect(MOCK_MARKERS).toContain("dj_cdj_pair");
  });

  it("finds nothing in a clean bundle", () => {
    writeFileSync(join(dir, "assets", "index.js"), "console.log('real app');");
    expect(findMockMarkers(dir)).toEqual([]);
  });

  it("finds a marker in a nested file and reports which one", () => {
    writeFileSync(join(dir, "assets", "chunk.js"), 'x={code:"dj_cdj_pair"}');
    const found = findMockMarkers(dir);
    expect(found).toHaveLength(1);
    expect(found[0]?.marker).toBe("dj_cdj_pair");
    expect(found[0]?.file.replaceAll("\\", "/")).toMatch(/assets\/chunk\.js$/);
  });

  it("CLI exits 0 on a clean dist, 1 on a marker, 2 when the directory is missing", () => {
    writeFileSync(join(dir, "assets", "index.js"), "ok");
    const run = (target: string) => spawnSync(process.execPath, [cli, target], { encoding: "utf8" });
    expect(run(dir).status).toBe(0);
    writeFileSync(join(dir, "assets", "leak.js"), "Par de reproductores CDJ");
    const dirty = run(dir);
    expect(dirty.status).toBe(1);
    expect(dirty.stderr).toContain("leak.js");
    expect(run(join(dir, "does-not-exist")).status).toBe(2);
  });
});
