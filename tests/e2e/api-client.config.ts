import { defineConfig } from "@playwright/test";

// Runs the real TypeScript client without a browser or live backend.
export default defineConfig({
  testDir: ".",
  testMatch: "security-api.spec.ts",
  workers: 1,
});
