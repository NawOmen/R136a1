import { defineConfig } from "@playwright/test";

// Перед запуском поднимите стек: docker compose -f infra/docker-compose.yml up --build
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:3000",
    headless: true,
    trace: "retain-on-failure",
  },
});
