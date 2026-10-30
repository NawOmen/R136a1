import { defineConfig, devices } from "@playwright/test";

// Build with same-origin public service paths as an HTTPS reverse-proxy deployment.
// All API responses in these browser scenarios are synthetic and intercepted.
const shared = ["proposal-flow-browser.spec.ts", "notifications-browser.spec.ts", "seller-offer-browser.spec.ts", "needs-controls-browser.spec.ts", "supplier-workflow-browser.spec.ts", "ideas-browser.spec.ts", "compatibility-browser.spec.ts", "mac-russian-browser.spec.ts", "requirements-browser.spec.ts", "route-boundaries.spec.ts", "russian-guidance.spec.ts"];
export default defineConfig({
  testDir: ".", workers: 1, timeout: 90_000,
  use: { baseURL: process.env.BASE_URL || "http://127.0.0.1:13003", headless: true, trace: "retain-on-failure" },
  webServer: {
    command: "pnpm --filter @sborka/web start --hostname 127.0.0.1 --port 13003",
    url: "http://127.0.0.1:13003", reuseExistingServer: !process.env.CI, cwd: "../..",
  },
  projects: [
    { name: "desktop-chromium", testMatch: shared, use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "safari-webkit", testMatch: shared, use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 1000 } } },
    { name: "iphone-webkit", testMatch: ["proposal-flow-browser.spec.ts", "notifications-browser.spec.ts", "seller-offer-browser.spec.ts", "needs-controls-browser.spec.ts", "supplier-workflow-browser.spec.ts", "ideas-browser.spec.ts", "compatibility-browser.spec.ts", "mac-russian-browser.spec.ts", "requirements-browser.spec.ts"], use: { ...devices["iPhone 13"] } },
    { name: "ipad-webkit", testMatch: ["proposal-flow-browser.spec.ts", "notifications-browser.spec.ts", "seller-offer-browser.spec.ts", "needs-controls-browser.spec.ts", "supplier-workflow-browser.spec.ts", "ideas-browser.spec.ts", "compatibility-browser.spec.ts", "mac-russian-browser.spec.ts"], use: { ...devices["iPad (gen 7)"] } },
    { name: "android-chromium", testMatch: ["proposal-flow-browser.spec.ts", "notifications-browser.spec.ts", "seller-offer-browser.spec.ts", "needs-controls-browser.spec.ts", "supplier-workflow-browser.spec.ts", "ideas-browser.spec.ts", "compatibility-browser.spec.ts", "mac-russian-browser.spec.ts", "requirements-browser.spec.ts"], use: { ...devices["Pixel 7"] } },
  ],
});
