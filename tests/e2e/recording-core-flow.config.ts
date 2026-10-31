import { defineConfig, devices } from "@playwright/test";

if (process.env.E2E_TEST_PROJECT !== "r136-recording") throw new Error("Нужен выделенный стенд r136-recording");
const endpoint=new URL(process.env.BASE_URL || "http://localhost:3000");
if (!["localhost","127.0.0.1","[::1]"].includes(endpoint.hostname) || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) throw new Error("Только локальный синтетический стенд записи");
process.env.E2E_RECORDING_SCENARIO="bolt-20000";
const live=process.env.RUN_LIVE_CORE_FLOW === "1";
export default defineConfig({
  testDir:".",testMatch:"marketplace.spec.ts",grep:live?/Живая локальная модель/:/Категория и подкатегория из формы/,
  workers:1,retries:0,timeout:600000,
  use:{baseURL:endpoint.origin,trace:"off",screenshot:"only-on-failure",video:"on"},
  projects:[{name:"recording-chromium",use:{...devices["Desktop Chrome"]}}],
});
