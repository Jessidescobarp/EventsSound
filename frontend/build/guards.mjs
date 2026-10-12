// Build-time guards that keep demo (mock) data out of production. Plain ESM so that
// vite.config.ts, the CI step and the unit tests can all import it without a loader.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

/** Distinctive strings that exist only in src/mocks/fakeApi.ts (the fake catalog). */
export const MOCK_MARKERS = ["dj_cdj_pair", "Par de reproductores CDJ", "pkg_basic_party"];

/** Throws when a production build would enable the fake API. */
export function assertNoMocksInProduction(mode, env) {
  if (mode === "production" && env.VITE_USE_MOCKS === "true") {
    throw new Error(
      "VITE_USE_MOCKS=true is not allowed in a production build (it would ship demo data). " +
        "Unset it, or build with --mode development for a demo build.",
    );
  }
}

/** Returns [{ file, marker }] for every file under `dir` containing a mock marker. */
export function findMockMarkers(dir) {
  const hits = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      hits.push(...findMockMarkers(path));
      continue;
    }
    const content = readFileSync(path, "utf8");
    for (const marker of MOCK_MARKERS) {
      if (content.includes(marker)) hits.push({ file: path, marker });
    }
  }
  return hits;
}
