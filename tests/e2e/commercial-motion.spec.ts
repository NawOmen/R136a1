import { expect, test } from "@playwright/test";
import { formatDate, formatDateTime } from "../../apps/web/app/lib/dates";
import { resolveAgentCategory } from "../../apps/web/app/lib/categoryProfiles";
import { displayValue } from "../../apps/web/app/lib/presentation";

const user = { id: "00000000-0000-4000-8000-000000000001", first_name: "Проверка", last_name: "Интерфейса", email: "synthetic@example.test", account_status: "active" };

test("calendar dates keep their day and use two-digit years", () => {
  expect(resolveAgentCategory("Продукты питания")).toBeNull();
  expect(resolveAgentCategory("Медицина и гигиена")).toBeNull();
  expect(formatDate("2026-01-09")).toBe("09.01.26");
  expect(formatDate("2024-02-29")).toBe("29.02.24");
  expect(formatDate("2026-02-30")).toBe("—");
  expect(formatDate(null, "Не ограничено")).toBe("Не ограничено");
  expect(displayValue("2026-10-19")).toBe("19.10.26");
  expect(formatDateTime("invalid")).toBe("—");
  expect(formatDateTime("2026-10-19T12:30:00Z")).toMatch(/^\d{2}\.\d{2}\.26, \d{2}:\d{2}$/);
});

for (const width of [1280, 390]) {
  test(`logo opens animation and account drawer fills viewport (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(() => localStorage.setItem("token", "synthetic-drawer-test"));
    await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/auth/me") ? { user, companies: [] } : [] }));
    await page.goto("/catalog");
    const avatar = page.getByRole("button", { name: "Открыть личный кабинет", exact: true });
    await avatar.click();
    const drawer = page.getByRole("dialog", { name: "Меню аккаунта", exact: true });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("link", { name: "Настройки", exact: true })).toBeVisible();
    expect(await drawer.evaluate(el => el.parentElement === document.body)).toBe(true);
    expect(await drawer.evaluate(el => Math.abs(el.getBoundingClientRect().height - window.innerHeight) < 2)).toBe(true);
    expect(await page.locator("#main-content").evaluate(el => el.inert)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(avatar).toBeFocused();
    expect(await page.locator("#main-content").evaluate(el => el.inert)).toBe(false);
    await page.getByRole("link", { name: "ПоРукам — на главную", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Товары и производство", exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Этапы взаимодействия", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("removed categories are absent from subscription choices", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-category-test"));
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/auth/me") ? { user, companies: [] } : [] }));
  await page.goto("/settings");
  const categories = page.getByRole("combobox", { name: "Категория для подписки", exact: true });
  await expect(categories).toBeVisible();
  const options = await categories.locator("option").allTextContents();
  expect(options).not.toContain("Продукты питания");
  expect(options).not.toContain("Медицина и гигиена");
  expect(options).toContain("Упаковка и тара");
});

test("reduced motion keeps the complete story readable without headline loops", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator('[data-still="true"]')).toBeVisible();
  await expect(page.getByRole("heading", { name: "Начните с задачи", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "От завода — к вашему офису", exact: true })).toBeVisible();
  const title = page.getByRole("heading", { name: "Товары и производство", exact: true }).locator("span");
  expect(await title.evaluate(el => getComputedStyle(el).animationName)).toBe("none");
});

test("animated catalog keeps filtering, sorting and focus usable", async ({ page }) => {
  const products = [
    { id: "first", name: "Картонная коробка", category: "Упаковка и тара", price_rub: "100", moq_units: 10, lead_time_days: 3, characteristics: {}, images: [], price_tiers: [] },
    { id: "second", name: "Крепёж", category: "Металлоизделия", price_rub: "20", moq_units: 20, lead_time_days: 5, characteristics: {}, images: [], price_tiers: [] },
  ];
  await page.route("**/api/**", route => route.fulfill({ json: route.request().url().includes("/products") ? products : [] }));
  await page.goto("/catalog");
  const cards = page.locator(".catalog-result-grid .market-product");
  await expect(cards).toHaveCount(2);
  await page.getByText("Фильтры и сортировка", { exact: true }).click();
  await page.getByRole("combobox", { name: "Сортировка", exact: true }).selectOption("price-asc");
  await expect(cards.first()).toContainText("Крепёж");
  const search = page.getByRole("textbox", { name: "Поиск товаров", exact: true });
  await search.fill("коробка");
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText("Картонная коробка");
  await expect(search).toBeFocused();
  await search.fill("");
  await expect(cards).toHaveCount(2);
});
