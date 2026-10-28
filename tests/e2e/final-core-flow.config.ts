import { defineConfig, devices } from "@playwright/test";

if (process.env.E2E_TEST_PROJECT !== "r136-fulltest" || process.env.RUN_LIVE_CORE_FLOW !== "1") {
  throw new Error("Нужны отдельный синтетический стенд r136-fulltest и RUN_LIVE_CORE_FLOW=1. Ручной путь не заменяет живой ИИ.");
}

const endpoint = new URL(process.env.BASE_URL || "http://localhost:3000");
if (!["localhost", "127.0.0.1", "[::1]"].includes(endpoint.hostname) || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) throw new Error("Финальный прогон разрешён только на локальном синтетическом стенде");

export default defineConfig({
  testDir: ".", testMatch: "marketplace.spec.ts", grep: /Живая локальная модель/,
  workers: 1, retries: 0, timeout: 600_000,
  use: { baseURL: process.env.BASE_URL || "http://localhost:3000", trace: "off", screenshot: "only-on-failure", video: "on" },
  projects: [{name:"final-chromium",use:{...devices["Desktop Chrome"]}},
    {name:"final-webkit",use:{...devices["Desktop Safari"]}}],
});
