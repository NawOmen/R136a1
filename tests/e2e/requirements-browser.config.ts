import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: ".", testMatch: ["mac-russian-browser.spec.ts", "requirements-browser.spec.ts", "route-boundaries.spec.ts", "russian-guidance.spec.ts", "design-browser.spec.ts", "guidance-browser.spec.ts", "hero-objects-browser.spec.ts", "liquid-surface-browser.spec.ts"], workers: 1,
  use: { baseURL: process.env.BASE_URL || "http://127.0.0.1:13003", headless: true, trace: "retain-on-failure" },
  webServer: { command: "pnpm --filter @sborka/web start --hostname 127.0.0.1 --port 13003", url: "http://127.0.0.1:13003", reuseExistingServer: !process.env.CI, cwd: "../.." },
});
