import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

// Сквозной happy-path без ИИ: покупатель публикует потребность, отдельный
// производитель отвечает, покупатель вручную подтверждает сделку.
test("потребность → предложение → сделка", async ({ page }) => {
  await login(page, "demo@demo.ru", "demo123");
  await expect(page.getByRole("heading", { name: "Личный кабинет" })).toBeVisible();

  await page.goto("/catalog");
  await expect(page).toHaveURL(/\/catalog/);

  await page.goto("/needs/new");
  await page.getByPlaceholder("Значение (например, 400)").first().fill("400");
  await page.getByPlaceholder("Значение (например, 400)").nth(1).fill("PE");
  await page.getByLabel("Объём, шт.").fill("1000");
  await page.getByLabel("Бюджет, ₽").fill("20000");
  await page.getByLabel("Срок выполнения").fill("2030-10-30");
  await page.getByLabel("Адрес доставки").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Создать и опубликовать" }).click();
  await expect(page).toHaveURL(/\/needs\/[0-9a-f-]+/);

  await page.evaluate(() => window.localStorage.clear());
  await login(page, "seller@demo.ru", "seller123");
  await page.goto("/seller/requests");
  await page.getByRole("button", { name: "Предложить условия" }).first().click();
  await page.getByLabel("Цена за единицу, ₽").fill("10");
  await page.getByLabel("Доступный объём, шт.").fill("1000");
  await page.getByLabel("MOQ предложения, шт.").fill("1000");
  await page.getByLabel("Логистика, ₽").fill("0");
  await page.getByLabel("Срок производства, дней").fill("7");
  await page.getByRole("button", { name: "Отправить предложение" }).click();
  await expect(page.getByText("Предложение отправлено")).toBeVisible();

  await page.evaluate(() => window.localStorage.clear());
  await login(page, "demo@demo.ru", "demo123");
  await page.goto("/needs");
  await page.locator('a.company-item[href^="/needs/"]').first().click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Выбрать предложение" }).click();
  await expect(page.getByRole("heading", { name: "Сделка заключена" })).toBeVisible();
});
