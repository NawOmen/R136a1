import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`unknown route has a Russian 404 and working navigation (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    await page.route("**/api/**", route => route.fulfill({ json: [] }));
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const response = await page.goto("/unknown-review-route");
    expect(response?.status()).toBe(404);
    await expect(page).toHaveTitle(/ПоРукам/);
    await expect(page.getByRole("heading", { name: "По этому адресу ничего нет" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("404.png"), fullPage: true });
    await page.getByRole("link", { name: "В каталог", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Каталог товаров", exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("render failure shows recovery UI and retry reloads the catalogue", async ({ page }, testInfo) => {
  let broken = true;
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    // Successful but malformed API data makes the page's render throw.
    // This checks the real Next boundary, rather than rendering its component alone.
    return route.fulfill({ json: path.endsWith("/products") && broken ? [null] : [] });
  });
  await page.goto("/catalog");
  const fallback = page.locator('.route-state[role="alert"]');
  await expect(fallback).toContainText("Не удалось открыть страницу");
  await expect(fallback).not.toContainText("TypeError");
  await page.screenshot({ path: testInfo.outputPath("recovery.png"), fullPage: true });
  broken = false;
  await page.getByRole("button", { name: "Попробовать снова" }).click();
  await expect(page.getByRole("heading", { name: "Каталог товаров", exact: true })).toBeVisible();
  await expect(fallback).toHaveCount(0);
});
