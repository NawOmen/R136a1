import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
const registry = JSON.parse(readFileSync(require.resolve("../../services/marketplace/app/category_registry.json"), "utf8"));

const companyId = "30000000-0000-4000-8000-000000000001";
const secondCompanyId = "30000000-0000-4000-8000-000000000002";
const needId = "30000000-0000-4000-8000-000000000003";
const productId = "30000000-0000-4000-8000-000000000004";
const otherProductId = "30000000-0000-4000-8000-000000000005";
const draftId = "30000000-0000-4000-8000-000000000006";
const need = {
  id: needId, category: "Строительство", subcategory: "Крепёж", revision: 1,
  characteristics: { unit: "шт", material: "Сталь", diameter_mm: 8, length_mm: 40, strength_class: "8.8" },
  volume_units: 20000, deadline_date: "2026-11-29", valid_until: "2026-11-29",
  status: "waiting_for_match", visibility: "open_anonymized",
};
const product = {
  id: productId, company_id: companyId, name: "Болт М8×40, класс 8.8", revision: 1,
  category: need.category, subcategory: need.subcategory, characteristics: need.characteristics,
  price_rub: "5.00", moq_units: 1000, lead_time_days: 2, stock_units: 40000,
  price_tiers: [{ min_units: 10000, unit_price_rub: "4.80" }], images: [], sources: [], is_published: true,
};

async function prepare(page: Page, options: { available?: number; sparse?: boolean; failure?: boolean; delayed?: boolean; warnings?: boolean; price?: string } = {}) {
  const drafts: Record<string, unknown>[] = [], previews: Record<string, unknown>[] = [], sends: Record<string, unknown>[] = [];
  const comparisons: string[] = [];
  let releaseDraft: (() => void) | undefined;
  const draftGate = new Promise<void>(resolve => { releaseDraft = resolve; });
  const seller = (id: string) => ({ id, display_name: `Синтетический поставщик ${id === companyId ? "А" : "Б"}`, full_name: "Синтетический поставщик", country: "RU", legal_form: "ООО", verification_status: "verified", membership: { can_buy: false, can_sell: true, is_admin: true } });
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-offer-browser"));
  page.on("pageerror", error => { throw error; });
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith("/categories/profiles")) return route.fulfill({ json: registry });
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user: { id: "synthetic-user", first_name: "Тест", last_name: "Продавец", account_status: "active" }, companies: [seller(companyId), seller(secondCompanyId)] } });
    if (path.includes("explain-seller-match")) comparisons.push(path);
    if (path.endsWith("/offer-draft")) {
      const body = request.postDataJSON(); drafts.push(body);
      if (options.delayed) await draftGate;
      if (options.failure) return route.fulfill({ status: 503, json: { detail: "Автозаполнение временно недоступно" } });
      return route.fulfill({ json: {
        id: draftId, need_id: needId, company_id: body.company_id, status: "draft",
        payload: { product_id: options.sparse ? null : productId, resource_kind: options.sparse ? "capacity" : "stock", source_updated_at: "2026-10-30T00:00:00Z",
          price_rub: options.sparse ? null : (options.price ?? "4.80"), available_units: options.sparse ? null : (options.available ?? 40000), moq_units: options.sparse ? null : 1000,
          lead_time_days: options.sparse ? null : 2, delivery_cost_rub: null, price_tiers: product.price_tiers },
        fields: [{ name: "price_rub", label: "Цена", value: options.sparse ? null : "4.80", source: "product", confirmed: !options.sparse, note: null }],
        missing: ["Стоимость логистики указывает человек"], warnings: ["Товар «Другая категория» не соответствует потребности", "Подходит несколько товаров", ...(options.available ? ["Свободного ресурса меньше запрошенного объёма"] : [])], explanation: "Из актуальных данных", created_at: null,
      } });
    }
    if (path.endsWith("/offers/preview")) {
      const body = request.postDataJSON(); previews.push(body);
      const blockers = options.available && body.available_units > options.available ? ["Недостаточно свободного ресурса"] : [];
      return route.fulfill({ json: { blockers, warnings: [], missing: [], can_send: blockers.length === 0 } });
    }
    if (path.endsWith("/offers") && request.method() === "POST") { sends.push(request.postDataJSON()); return route.fulfill({ status: 201, json: { id: "synthetic-offer", sending_warnings: options.warnings ? ["Проверьте подтверждения"] : [] } }); }
    if (path.endsWith("/category-profile")) return route.fulfill({ json: { state: "current", current: null, previous: null, changes: [] } });
    if (path.endsWith("/products")) return route.fulfill({ json: [{ ...product, price_rub: options.price ?? product.price_rub }, { ...product, id: otherProductId, name: "Болт М8×40, другая партия" }] });
    if (path.endsWith("/needs")) return route.fulfill({ json: [need] });
    return route.fulfill({ json: [] });
  });
  await page.goto("/seller/requests");
  const card = page.locator(`[data-need-id="${needId}"]`);
  await expect(card).toBeVisible();
  return { card, drafts, previews, sends, comparisons, releaseDraft: () => releaseDraft!() };
}

async function open(page: Page, state: Awaited<ReturnType<typeof prepare>>) {
  await state.card.getByRole("button", { name: "Предложить условия", exact: true }).click();
  await expect(page.locator(`#offer_units_${needId}`)).toBeVisible();
}

async function deliveryAndTax(card: ReturnType<Page["locator"]>) {
  await card.getByRole("combobox", { name: /^Условия доставки/ }).selectOption("included");
  await card.getByRole("combobox", { name: /^Налоговая база/ }).selectOption("no_vat");
  await card.getByLabel("Условия и место получения", { exact: true }).fill("Доставка в Москву");
}

test("proposal opens prefilled, accepts unchanged values and sends only after human confirmation", async ({ page }, testInfo) => {
  const state = await prepare(page);
  await open(page, state);
  await expect(page.locator(`#offer_price_${needId}`)).toHaveValue("4.80");
  await expect(page.locator(`#offer_units_${needId}`)).toHaveValue("20000");
  await expect(page.locator(`#offer_moq_${needId}`)).toHaveValue("1000");
  await expect(page.locator(`#offer_lead_${needId}`)).toHaveValue("2");
  await expect(page.locator(`#offer_resource_${needId}`)).toHaveValue("stock");
  await expect(page.locator(`#offer_product_${needId}`)).toHaveValue(productId);
  await expect(state.card.getByRole("combobox", { name: /^Условия доставки/ })).toHaveValue("unknown");
  await expect(state.card.getByRole("combobox", { name: /^Налоговая база/ })).toHaveValue("unknown");
  await expect(page.locator(`#offer_delivery_${needId}`)).toHaveValue("");
  await expect(state.card.locator(".alert-warning,.draft-panel,.offer-sources,.match-explanation")).toHaveCount(0);
  await expect(state.card.getByText("Откуда взяты условия", { exact: true })).toHaveCount(0);
  await expect(state.card.getByRole("button", { name: "Почему подходит?", exact: true })).toHaveCount(0);
  await expect(state.card.getByText("Товар «Другая категория» не соответствует потребности", { exact: true })).toHaveCount(0);
  expect(state.comparisons).toHaveLength(0);
  expect(state.drafts).toHaveLength(1);
  expect(state.sends).toHaveLength(0);
  expect(state.previews).toHaveLength(0);
  // Layout checks use the actual open form, in all browser/device projects.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  const fields = state.card.locator('.seller-offer__fields');
  await fields.scrollIntoViewIfNeeded();
  await page.getByRole("heading", { name: "Потребности покупателей", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("prefilled-offer.png"), fullPage: true, animations: "disabled" });
  await page.evaluate(() => document.documentElement.dataset.theme = "dark");
  await page.screenshot({ path: testInfo.outputPath("prefilled-offer-dark.png"), fullPage: true, animations: "disabled" });
  await deliveryAndTax(state.card);
  await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
  await expect(state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true })).toBeVisible();
  expect(state.sends).toHaveLength(0);
  await state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true }).click();
  await expect(state.card.getByText("Предложение отправлено. Ожидайте решения покупателя.", { exact: true })).toBeVisible();
  expect(state.sends).toHaveLength(1);
  expect(state.sends[0]).toMatchObject({ draft_id: draftId, price_rub: "4.80", available_units: 20000, moq_units: 1000, lead_time_days: 2, delivery_cost_rub: "0", resource_kind: "stock", product_id: productId, price_tiers: [] });
});

test("each term is independently editable, exact price survives and edits invalidate a preview", async ({ page }) => {
  const state = await prepare(page);
  await open(page, state);
  await deliveryAndTax(state.card);
  await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
  await expect(state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true })).toBeVisible();
  await page.locator(`#offer_price_${needId}`).fill("4.12345");
  await expect(page.locator(`#offer_price_${needId}`)).toHaveValue("4.12");
  await expect(page.locator(`#offer_units_${needId}`)).toHaveValue("20000");
  await expect(state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true })).toHaveCount(0);
  await expect(state.card.getByText("Условия изменились после проверки. Проверьте условия заново.", { exact: true })).toBeVisible();
  await page.locator(`#offer_units_${needId}`).fill("15000");
  await page.locator(`#offer_moq_${needId}`).fill("500");
  await page.locator(`#offer_lead_${needId}`).fill("3");
  await state.card.getByRole("combobox", { name: /^Условия доставки/ }).selectOption("separate");
  await page.locator(`#offer_delivery_${needId}`).fill("1500.50");
  await state.card.getByRole("combobox", { name: /^Налоговая база/ }).selectOption("includes_vat");
  await state.card.getByLabel("Включённый НДС, %").fill("20");
  await state.card.getByLabel("Исключения и ограничения", { exact: true }).fill("Отгрузка одной партией");
  await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
  await state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true }).click();
  await expect.poll(() => state.sends.length).toBe(1);
  expect(state.sends[0]).toMatchObject({ draft_id: draftId, price_rub: "4.12", available_units: 15000, moq_units: 500, lead_time_days: 3, delivery_cost_rub: "1500.50", price_tiers: [], commercial_terms: { tax_basis: "includes_vat", vat_rate_pct: "20", delivery_method: "separate", exceptions: "Отгрузка одной партией" } });
});

test("changing the source or SKU sends the chosen source rather than the original draft binding", async ({ page }) => {
  const state = await prepare(page, { warnings: true });
  await open(page, state);
  await deliveryAndTax(state.card);
  await page.locator(`#offer_resource_${needId}`).selectOption("stock");
  await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
  await expect.poll(() => state.previews.length).toBe(1);
  expect(state.previews[0]).toMatchObject({ draft_id: draftId });
  await page.locator(`#offer_resource_${needId}`).selectOption("capacity");
  await page.locator(`#offer_resource_${needId}`).selectOption("stock");
  await page.locator(`#offer_product_${needId}`).selectOption(otherProductId);
  await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
  await state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true }).click();
  await expect(state.card.getByText("Предложение отправлено. Ожидайте решения покупателя.", { exact: true })).toBeVisible();
  expect(state.sends[0]).toMatchObject({ resource_kind: "stock", product_id: otherProductId, price_tiers: [] });
  expect(state.sends[0]).not.toHaveProperty("draft_id");
  await expect(state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true })).toHaveCount(0);
});

test("resource shortage stays explicit, does not silently reduce the buyer quantity and blocks sending", async ({ page }) => {
  const state = await prepare(page, { available: 12000 });
  await open(page, state);
  await expect(page.locator(`#offer_units_${needId}`)).toHaveValue("20000");
  await expect(state.card.locator(".alert-warning")).toHaveCount(0);
  await deliveryAndTax(state.card);
  await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Недостаточно свободного ресурса" })).toBeVisible();
  await expect(state.card.getByRole("button", { name: "Подтвердить отправку КП", exact: true })).toHaveCount(0);
  expect(state.sends).toHaveLength(0);
});

for (const failure of [false, true]) {
  test(`missing catalog data stays explicit and manual entry remains possible (${failure ? "failed" : "sparse"} draft)`, async ({ page }) => {
    const state = await prepare(page, { sparse: true, failure });
    await open(page, state);
    await expect(page.locator(`#offer_units_${needId}`)).toHaveValue("20000");
    await expect(page.locator(`#offer_price_${needId}`)).toHaveValue("");
    await expect(page.locator(`#offer_moq_${needId}`)).toHaveValue("");
    await expect(page.locator(`#offer_lead_${needId}`)).toHaveValue("");
    await expect(page.locator(`#offer_delivery_${needId}`)).toHaveValue("");
    if (failure) await expect(page.getByRole("alert").filter({ hasText: "Автозаполнение временно недоступно" })).toBeVisible();
    await page.locator(`#offer_price_${needId}`).fill("5");
    await page.locator(`#offer_moq_${needId}`).fill("1000");
    await page.locator(`#offer_lead_${needId}`).fill("2");
    await deliveryAndTax(state.card);
    await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
    await expect.poll(() => state.previews.length).toBe(1);
    expect(state.sends).toHaveLength(0);
    await state.card.getByRole("button", { name: "Отмена", exact: true }).click();
    await expect(page.locator(`#offer_price_${needId}`)).toHaveCount(0);
    expect(state.sends).toHaveLength(0);
  });
}

test("late prefill for another company cannot open a form or leak its values", async ({ page }) => {
  const state = await prepare(page, { delayed: true });
  await state.card.getByRole("button", { name: "Предложить условия", exact: true }).click();
  await expect.poll(() => state.drafts.length).toBe(1);
  const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith("/offer-draft"));
  await page.locator("#seller_company").selectOption(secondCompanyId);
  state.releaseDraft();
  await response;
  await expect(page.getByRole("heading", { name: "Условия предложения", exact: true })).toHaveCount(0);
  await expect(state.card.getByRole("button", { name: "Предложить условия", exact: true })).toBeEnabled();
  expect(state.previews).toHaveLength(0);
  expect(state.sends).toHaveLength(0);
});


test("prefilled new quotes and new delivery entries use at most two decimal places", async ({ page }) => {
  const state = await prepare(page, { price: "4.123456789012" });
  await open(page, state);
  await expect(page.locator(`#offer_price_${needId}`)).toHaveValue("4.12");
  await deliveryAndTax(state.card);
  await state.card.getByRole("combobox", { name: /^Условия доставки/ }).selectOption("separate");
  await page.locator(`#offer_delivery_${needId}`).fill("1000.555");
  await expect(page.locator(`#offer_delivery_${needId}`)).toHaveValue("1000.56");
  await page.locator(`#offer_price_${needId}`).fill("");
  await page.locator(`#offer_price_${needId}`).pressSequentially("4.09");
  await expect(page.locator(`#offer_price_${needId}`)).toHaveValue("4.09");
  await page.locator(`#offer_price_${needId}`).fill("9.999");
  await expect(page.locator(`#offer_price_${needId}`)).toHaveValue("10.00");
  await state.card.getByRole("button", { name: "Проверить условия", exact: true }).click();
  await expect.poll(() => state.previews.length).toBe(1);
  expect(state.previews[0]).toMatchObject({ price_rub: "10.00", delivery_cost_rub: "1000.56" });
  expect(state.sends).toHaveLength(0);
});

test("catalogue price and tiers share kopeck input while quantities retain their precision", async ({ page }) => {
  await prepare(page);
  await page.goto("/seller/products");
  const price = page.locator("#product_price");
  await expect(price).toBeVisible();
  await price.fill("12.345");
  await expect(price).toHaveValue("12.35");
  await page.getByRole("button", { name: "+ Добавить ценовую ступень", exact: true }).click();
  const tier = page.getByLabel("Цена ступени", { exact: true });
  await expect(tier).toHaveValue("12.35");
  await tier.fill("0.999");
  await expect(tier).toHaveValue("1.00");
  const quantity = page.getByLabel("Объём ступени", { exact: true });
  await quantity.fill("1000.123456");
  await expect(quantity).toHaveValue("1000.123456");
});


test("showing a saved subkopeck catalogue price does not force a new price", async ({ page }) => {
  await prepare(page, { price: "0.0001" });
  await page.goto("/seller/products");
  await page.getByRole("button", { name: "Редактировать", exact: true }).first().click();
  const price = page.locator("#product_price");
  await expect(price).toHaveValue("0.00");
  await expect(price).toHaveAttribute("title", /Сохранённая сумма/);
  expect(await price.evaluate((element: HTMLInputElement) => element.checkValidity())).toBe(true);
  await price.fill("1.235");
  await expect(price).toHaveValue("1.24");
  await expect(price).toHaveAttribute("min", "0.01");
});
