// CI step after `npm run build`: fail if the bundle contains demo data.
// Usage: node build/check-no-mocks.mjs [dist-dir]   (exit 0 clean, 1 marker found, 2 no such dir)
import { existsSync } from "node:fs";
import { findMockMarkers } from "./guards.mjs";

const dir = process.argv[2] ?? "dist";
if (!existsSync(dir)) {
  console.error(`check-no-mocks: directory not found: ${dir}`);
  process.exit(2);
}
const hits = findMockMarkers(dir);
if (hits.length > 0) {
  for (const hit of hits) console.error(`check-no-mocks: marker "${hit.marker}" found in ${hit.file}`);
  process.exit(1);
}
console.log(`check-no-mocks: ${dir} is clean`);
