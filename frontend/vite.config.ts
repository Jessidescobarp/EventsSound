import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import { assertNoMocksInProduction } from "./build/guards.mjs";

export default defineConfig(({ mode }) => {
  // Refuse to ship demo data: also sees values coming from the process environment.
  assertNoMocksInProduction(mode, loadEnv(mode, "..", "VITE_"));
  return {
    plugins: [react(), tailwindcss()],
    // Read VITE_* variables from the single root .env. Only VITE_-prefixed keys reach the bundle.
    envDir: "..",
    test: {
      environment: "jsdom",
      setupFiles: ["./src/setupTests.ts"],
      restoreMocks: true,
      unstubEnvs: true,
      unstubGlobals: true,
    },
  };
});
