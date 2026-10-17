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
