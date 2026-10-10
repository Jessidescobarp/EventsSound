import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Read VITE_* variables from the single root .env. Only VITE_-prefixed keys reach the bundle.
  envDir: "..",
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
  },
});
