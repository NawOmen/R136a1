import { expect, test } from "@playwright/test";
import { russianMessage, validationMessage } from "../../apps/web/app/lib/russianMessages";
import { displayValue, russianLabel } from "../../apps/web/app/lib/presentation";
import { canonicalCharacteristicKey } from "../../apps/web/app/lib/categoryProfiles";
import { parseSizeRanges } from "../../apps/web/app/lib/capabilities";

test("errors, statuses and structured values have Russian presentation without changing keys", () => {
  expect(russianMessage("Failed to fetch")).toContain("Не удалось связаться");
  expect(russianMessage("Internal Server Error")).toContain("Не удалось выполнить");
  expect(validationMessage({ type: "missing", loc: ["body", "unmapped_field"], msg: "Field required" }, {})).toBe("«Значение»: заполните обязательное поле");
  expect(validationMessage({ type: "int_parsing", msg: "Input should be a valid integer", loc: ["body", "quantity_units"] }, { quantity_units: "Количество" })).toBe("«Количество»: введите корректное число");
  expect(displayValue({ status: "in_production", estimate_complete: false })).toBe("Статус: Производство; Полнота сметы: Нет");
  expect(russianLabel("not_a_real_status", "Статус уточняется")).toBe("Статус уточняется");
  expect(canonicalCharacteristicKey("Материал")).toBe("material");
  expect(parseSizeRanges("Диаметр, мм: 10: 120")).toEqual({ diameter_mm: [10, 120] });
  expect(displayValue("Qwen")).toBe("Qwen");
});

const company = { id: "00000000-0000-4000-8000-000000000010", display_name: "Синтетическая компания", country: "RU", verification_status: "draft", membership: { can_buy: true, can_sell: true, is_admin: true } };
const user = { id: "00000000-0000-4000-8000-000000000001", first_name: "Проверка", last_name: "Интерфейса", account_status: "active" };

test("first login opens a scoped next action instead of declaring a draft company ready", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-guidance"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user, companies: [company] } });
    if (path.endsWith("/next-step")) {
      expect(new URL(route.request().url()).searchParams.get("company_id")).toBe(company.id);
      return route.fulfill({ json: { title: "Завершите проверку компании", description: "Публикация доступна после проверки.", href: `/company/${company.id}` } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Завершите проверку компании" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Продолжить", exact: true })).toHaveAttribute("href", `/company/${company.id}`);
  await expect(page.getByText(/готова к работе/)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Выберите рабочий путь" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Закупки и статистика", exact: false })).toBeHidden();
  await page.getByText("Все рабочие разделы", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Закупки и статистика", exact: false })).toBeVisible();
});

test("native required field validation is Russian even with an English browser", async ({ page }) => {
  await page.goto("/register");
  await page.getByRole("button", { name: /Зарегистрироваться|Создать аккаунт/ }).click();
  const message = await page.locator('input[required]').first().evaluate(input => (input as HTMLInputElement).validationMessage);
  expect(message).toBe("Заполните обязательное поле.");
});

for (const mode of ["buy", "sell"] as const) {
  test(`market needs navigation follows selected work mode: ${mode}`, async ({ page }) => {
    await page.addInitScript(({ userId, companyId, mode }) => {
      localStorage.setItem("token", "synthetic-navigation");
      localStorage.setItem(`porukam:work-mode:${userId}:${companyId}`, mode);
    }, { userId: user.id, companyId: company.id, mode });
    await page.route("**/api/**", route => {
      if (new URL(route.request().url()).pathname.endsWith("/auth/me")) return route.fulfill({ json: { user, companies: [company] } });
      return route.fulfill({ json: [] });
    });
    await page.goto("/catalog");
    await expect(page.getByRole("navigation", { name: "Раздел рынка" }).getByRole("link", { name: "Потребности" }))
      .toHaveAttribute("href", mode === "buy" ? "/needs" : "/seller/requests");
  });
}

test("homepage distinguishes unavailable offers from an empty catalogue and retries", async ({ page }) => {
  let failed = true;
  await page.route("**/api/**", route => route.fulfill(failed
    ? { status: 503, json: { detail: "Предложения временно недоступны" } }
    : { json: [] }));
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось загрузить предложения" })).toBeVisible();
  await expect(page.getByText("Предложений пока нет", { exact: true })).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Повторить загрузку", exact: true }).click();
  await expect(page.getByText("Предложений пока нет", { exact: true })).toBeVisible();
});

test("optional product checks fail independently without hiding product or implying admission", async ({ page }) => {
  const product = { id: "00000000-0000-4000-8000-000000000090", name: "Синтетический товар", category: "Упаковка и тара", subcategory: "Бумажные стаканы", characteristics: {}, images: [], price_rub: "10.5", price_tiers: [], moq_units: 100, lead_time_days: 3, producer: { display_name: "Проверочный производитель", company_id: company.id, rating: null, reviews_count: 0 } };
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill(path.endsWith("/detail") ? { json: product } : { status: 503, json: { detail: "Временно недоступно" } });
  });
  await page.goto(`/catalog/${product.id}`);
  await expect(page.getByRole("heading", { name: product.name, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Запросить условия", exact: true })).toBeVisible();
  await expect(page.getByText("История цен временно недоступна.", { exact: false })).toBeVisible();
  await expect(page.getByText("Не удалось загрузить сведения о допуске.", { exact: false })).toBeVisible();
  await expect(page.getByText("Для этой категории правила проверки документов ещё не настроены.", { exact: false })).toHaveCount(0);
});

test("guest mobile access includes login, usable theme and reachable form before marketing copy", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await expect(page.locator("header").getByRole("link", { name: "Войти", exact: true })).toBeVisible();
  const email = page.getByLabel("Электронная почта", { exact: false });
  await expect(email).toBeInViewport();
  await page.getByRole("button", { name: "Включить светлую тему" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Включить тёмную тему" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
