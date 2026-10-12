import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { installMocks } = vi.hoisted(() => ({ installMocks: vi.fn() }));
vi.mock("./mocks/fakeApi", () => ({ installMocks }));
vi.mock("react-dom/client", () => ({ createRoot: vi.fn() }));

const render = vi.fn();

async function boot(flag?: string) {
  vi.resetModules();
  if (flag !== undefined) vi.stubEnv("VITE_USE_MOCKS", flag);
  document.body.innerHTML = '<div id="root"></div>';
  await import("./main");
  await vi.waitFor(() => expect(render).toHaveBeenCalledTimes(1));
}

describe("main.tsx mock gate", () => {
  beforeEach(() => {
    installMocks.mockClear();
    render.mockClear();
    vi.mocked(createRoot).mockReset();
    vi.mocked(createRoot).mockReturnValue({ render, unmount: vi.fn() });
  });

  it("installs the fake API, before rendering, only for the exact string 'true'", async () => {
    await boot("true");
    expect(installMocks).toHaveBeenCalledTimes(1);
    const installedAt = installMocks.mock.invocationCallOrder[0] ?? Infinity;
    const renderedAt = render.mock.invocationCallOrder[0] ?? -Infinity;
    expect(installedAt).toBeLessThan(renderedAt);
  });

  it.each(["false", "1", "", "TRUE", "True", "yes", " true", "true "])(
    "does not install the fake API for %j but still renders",
    async (flag) => {
      await boot(flag);
      expect(installMocks).not.toHaveBeenCalled();
      expect(render).toHaveBeenCalledTimes(1);
    },
  );

  it("never installs the fake API in production mode, even if the flag is true (defence in depth)", async () => {
    vi.stubEnv("MODE", "production");
    await boot("true");
    expect(installMocks).not.toHaveBeenCalled();
    expect(render).toHaveBeenCalledTimes(1);
  });

  it("installs in development mode for a demo build", async () => {
    vi.stubEnv("MODE", "development");
    await boot("true");
    expect(installMocks).toHaveBeenCalledTimes(1);
  });

  it("does not install the fake API when the variable is not defined", async () => {
    await boot();
    expect(installMocks).not.toHaveBeenCalled();
  });
});

describe("single shared predicate", () => {
  const sourceFiles = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return sourceFiles(path);
      return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name) ? [path] : [];
    });

  it("only src/env.ts reads VITE_USE_MOCKS; everything else calls isMockMode()", () => {
    const root = join(import.meta.dirname);
    const readers = sourceFiles(root)
      .filter((file) => readFileSync(file, "utf8").includes("VITE_USE_MOCKS"))
      .map((file) => relative(root, file).replaceAll("\\", "/"));
    expect(readers).toEqual(["env.ts"]);
  });
});
