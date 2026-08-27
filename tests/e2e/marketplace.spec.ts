import { expect, test } from "@playwright/test";

// Сквозной happy-path без ИИ: вход → каталог → создание потребности покупателем.
// Использует проверенную демо-компанию (demo@demo.ru / demo123, оба режима).
test("вход и создание потребности", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@demo.ru");
  await page.getByLabel("Пароль").fill("demo123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Личный кабинет" })).toBeVisible();

  await page.goto("/catalog");
  await expect(page).toHaveURL(/\/catalog/);

  await page.goto("/needs/new");
  await page.getByPlaceholder("Значение (например, 400)").first().fill("400");
  await page.getByPlaceholder("Значение (например, 400)").nth(1).fill("PE");
  await page.getByLabel("Объём, шт.").fill("1000");
  await page.getByLabel("Бюджет, ₽").fill("20000");
  await page.getByLabel("Срок выполнения").fill("2026-10-30");
  await page.getByLabel("Адрес доставки").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Создать потребность" }).click();
  await expect(page).toHaveURL(/\/needs\/[0-9a-f-]+/);
});
