import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

  it("covers the fake login fixtures too", () => {
    expect(MOCK_MARKERS).toEqual(expect.arrayContaining(["demo-password", "demo.admin.token"]));
  });

  it("uses a distinctive fake-catalog marker", () => {
    expect(MOCK_MARKERS).toContain("dj_cdj_pair");
  });

  it("every marker really exists in the fake API sources (the guard cannot go stale)", () => {
    const mocks = join(import.meta.dirname, "..", "src", "mocks");
    const source = readdirSync(mocks)
      .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
      .map((name) => readFileSync(join(mocks, name), "utf8"))
      .join("\n");
    for (const marker of MOCK_MARKERS) expect(source).toContain(marker);
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

describe("vite.config.ts wiring (real vite build)", () => {
  const vite = join(import.meta.dirname, "..", "node_modules", "vite", "bin", "vite.js");
  const build = (args: string[], env: Record<string, string>) => {
    const out = mkdtempSync(join(tmpdir(), "vite-out-"));
    try {
      return spawnSync(process.execPath, [vite, "build", "--outDir", out, "--emptyOutDir", ...args], {
        cwd: join(import.meta.dirname, ".."),
        encoding: "utf8",
        env: { ...process.env, VITE_API_BASE_URL: "https://api.example", ...env },
      });
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  };

  it("fails a production build when VITE_USE_MOCKS=true", () => {
    const result = build([], { VITE_USE_MOCKS: "true" });
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("VITE_USE_MOCKS");
  }, 60_000);

  it("allows a development-mode (demo) build with VITE_USE_MOCKS=true", () => {
    const result = build(["--mode", "development"], { VITE_USE_MOCKS: "true" });
    expect(result.status).toBe(0);
  }, 60_000);
});
