import { expect, test, type Page } from "@playwright/test";

const companyId = "00000000-0000-4000-8000-000000000010";
const needId = "00000000-0000-4000-8000-000000000020";
const addressId = "00000000-0000-4000-8000-000000000030";
const productId = "00000000-0000-4000-8000-000000000040";
const company = { id: companyId, display_name: "Тестовая компания", full_name: "Тестовая компания", country: "RU", legal_form: "ООО", verification_status: "verified", membership: { can_buy: true, can_sell: true, is_admin: true } };
const product = { id: productId, name: "Коробки для бизнеса", company_id: companyId, category: "Упаковка и тара", subcategory: "Коробки", characteristics: { unit: "шт" }, price_rub: "38.123456789123", moq_units: 100, lead_time_days: 7, images: [], price_tiers: [], producer: { company_id: companyId, display_name: "Тестовый производитель", reviews_count: 0 } };
const need = { id: needId, company_id: companyId, category: "Упаковка и тара", subcategory: "Коробки", status: "open_for_offers", visibility: "public", revision: 1, volume_units: 125.125, budget_rub: "5000.125", deadline_date: "2026-11-01", valid_until: "2026-10-30", delivery_address_id: addressId, characteristics: { unit: "шт" }, files: [], requirements_evidence: { fields: { delivery_address_id: { value: addressId, origin: "manual", confirmed_at: "2026-10-25T12:00:00Z", sources: [] } } } };
const history = Array.from({ length: 8 }, (_, i) => ({ date: `2026-10-${String(i * 3 + 1).padStart(2, "0")}`, average_unit_price_rub: String(35 + i), offers_count: 1 }));

async function prepare(page: Page, emptyCompany = false) {
  page.on("pageerror", error => { throw error; });
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-ideas-ui"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path.endsWith("/auth/me")) json = { user: { id: "synthetic-user", first_name: "Тест", last_name: "Интерфейс", account_status: "active" }, companies: emptyCompany ? [] : [company] };
    else if (path.endsWith("/next-step")) json = {title:"Создайте потребность", description:"Опишите закупку", href:"/needs/new"};
    else if (path.endsWith("/admission")) json = {checklist:[],advisories:[],supported:false,summary:"Документы уточняются"};
    else if (path.endsWith("/categories/profiles")) json = { groups: [], characteristic_fields: {} };
    else if (path.endsWith("/products")) json = [product];
    else if (path.endsWith(`/products/${productId}/detail`)) json = product;
    else if (path.includes("/price-index/")) json = history;
    else if (path.endsWith("/addresses")) json = [{ id: addressId, company_id: companyId, city: "Казань", address: "ул. Тестовая, 10", region: "Татарстан", is_default: true }];
    else if (path.endsWith("/needs/mine")) json = [need];
    else if (path.endsWith(`/needs/${needId}`)) json = need;
    else if (path.endsWith("/price-forecasts")) json = { contract_version: "price-forecast-1", status: "ready", observations: 8, history_from: history[0].date, history_to: history.at(-1)!.date, ai_status: "completed", points: [{ date: "2026-11-01", price_rub: "43.125" }], notes: ["Расчётный тренд, не гарантия будущей цены."] };
    else if (path.endsWith("/buyer-agent/runs")) return route.fulfill({ status: 503, json: { detail: "Локальная Qwen недоступна или вернула неверный JSON" } });
    return route.fulfill({ json });
  });
}

test("footer disclosure closes on navigation, outside click and Escape", async ({ page }) => {
  await prepare(page); await page.goto("/");
  const menu = page.locator(".footer-more");
  await menu.locator("summary").click();
  await menu.getByRole("link", { name: "Новости", exact: true }).click();
  await expect(page).toHaveURL(/\/info\/news$/);
  await expect(menu).not.toHaveAttribute("open");
  await expect(page.locator(".news-entry")).toHaveCount(6);
  await menu.locator("summary").click(); await page.keyboard.press("Escape");
  await expect(menu).not.toHaveAttribute("open");
  await menu.locator("summary").click(); await page.locator("h1").click();
  await expect(menu).not.toHaveAttribute("open");
});

test("legal copy keeps documents and omits internal revision identifiers", async ({ page }) => {
  await prepare(page);
  for (const slug of ["legal", "privacy"]) {
    await page.goto(`/info/${slug}`, { waitUntil: "networkidle" });
    await expect(page.locator("main")).not.toContainText(/Редакция|rules-2|privacy-2/);
    await expect(page.getByRole("link", { name: "Скачать документ" })).toBeVisible();
  }
});

test("company form aligns hints, validates INN and stays still while focused", async ({ page, isMobile }) => {
  await prepare(page); await page.goto("/company/new");
  const inn = page.locator("#inn"), form = page.locator("main form"), hint = page.locator(".form-required-note");
  await expect(page.locator("#inn-hint")).toHaveText("10 цифр для ООО");
  expect((await hint.boundingBox())!.x).toBeGreaterThanOrEqual((await form.boundingBox())!.x);
  await inn.fill("12345"); expect(await inn.evaluate((input: HTMLInputElement) => input.validity.patternMismatch)).toBe(true);
  await page.locator("#legal_form").selectOption("ИП");
  await expect(page.locator("#inn-hint")).toHaveText("12 цифр для ИП");
  await expect(inn).toHaveAttribute("maxlength", "12");
  await inn.fill("123456789012"); expect(await inn.evaluate((input: HTMLInputElement) => input.checkValidity())).toBe(true);
  await inn.focus();
  if (!isMobile) await inn.hover();
  await expect.poll(() => inn.evaluate(el => getComputedStyle(el).transform)).toBe("none");
  if (!isMobile) { await page.locator("#legal_form").hover(); await expect.poll(() => page.locator("#legal_form").evaluate(el => getComputedStyle(el).transform)).toBe("none"); }
});

test("empty company panel places a larger creation action and omits onboarding", async ({ page }) => {
  await prepare(page, true); await page.goto("/dashboard");
  const panel = page.locator(".my-companies"), action = panel.getByRole("link", { name: "Создать компанию" });
  await expect(action).toBeVisible(); expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(48);
  await expect(page.getByText("Первые шаги", { exact: true })).toHaveCount(0);
  if (page.viewportSize()!.width > 600) { const a = (await action.boundingBox())!, p = (await panel.boundingBox())!; expect(Math.abs(a.y + a.height / 2 - p.y - p.height / 2)).toBeLessThan(2); }
});

test("my needs use the header search and detail resolves the delivery address", async ({ page }) => {
  await prepare(page); await page.goto("/needs");
  await expect(page.getByPlaceholder("Категория или статус потребности")).toHaveCount(0);
  await page.locator(`a[href='/needs/${needId}']`).click();
  await expect(page.locator(".need-summary")).toContainText("Казань, ул. Тестовая, 10");
  await expect(page.locator(".need-summary")).toContainText("125,13 шт");
  await expect(page.locator(".need-summary")).toContainText("5 000,13 ₽");
  await expect(page.locator(".need-summary")).toContainText("01.11.26");
  await page.getByText("Требования, источники и история", { exact: true }).click();
  await expect(page.locator(".need-requirements")).toContainText("Казань, ул. Тестовая, 10");
  await expect(page.locator("main")).not.toContainText(addressId);
  await expect(page.getByRole("heading", { name: /Предложения/ })).toBeVisible();
});

test("AI failure uses clear Russian copy and preserves the written request", async ({ page }) => {
  await prepare(page); await page.goto("/needs/new");
  await expect(page.locator(".need-company-name")).toContainText("Тестовая компания");
  await expect(page.getByText("Закупка с ИИ", { exact: true })).toHaveCount(0);
  await page.locator("#request_description").fill("Нужны коробки, 100 штук");
  await page.getByRole("button", { name: "Заполнить с ИИ", exact: true }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("Модель ИИ не работает. Заполните карточку ниже вручную или повторите анализ.");
  await expect(page.locator("#request_description")).toHaveValue("Нужны коробки, 100 штук");
});

test("price history expands and forecast stays separate from the sale price", async ({ page }, info) => {
  await prepare(page); await page.goto(`/catalog/${productId}`);
  await expect(page.locator(".price-history-chart")).toBeVisible();
  await expect(page.locator(".product-price-history .price-index>div:visible")).toHaveCount(6);
  await page.getByText("Вся история (8 дат)", { exact: true }).click();
  await expect(page.locator(".product-price-history .price-index>div:visible")).toHaveCount(8);
  await page.getByRole("button", { name: "Прогноз с ИИ", exact: true }).click();
  await expect(page.locator(".forecast-points")).toContainText("43,13 ₽");
  await expect(page.locator(".product-price-history")).toContainText("ИИ-анализ выполнен");
  await expect(page.locator(".product-price")).toContainText("38,12 ₽");
  await expect(page.locator(".product-price-history")).toContainText("не гарантия будущей цены");
  await page.screenshot({ path: info.outputPath("product.png"), fullPage:true, animations:"disabled" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("header examples animate only outside focused input and respect reduced motion", async ({ page }) => {
  await prepare(page); await page.goto("/");
  const search = page.getByRole("textbox", { name: "Поиск по маркетплейсу" });
  await expect.poll(() => search.getAttribute("placeholder"), { timeout: 6000 }).not.toBe("Найти товар или категорию");
  await search.fill("Мой запрос"); await page.waitForTimeout(300);
  await expect(search).toHaveValue("Мой запрос");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await search.fill(""); await search.blur();
  await expect(search).toHaveAttribute("placeholder", "Найти товар или категорию");
  expect(await page.locator(".storefront-request__symbol svg").evaluate(el => getComputedStyle(el).animationName)).toBe("none");
});
