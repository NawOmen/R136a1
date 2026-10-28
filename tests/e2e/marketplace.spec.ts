import { completeLiveClarifications } from "./live-core-clarifications";
import { canonicalCharacteristicKey } from "../../apps/web/app/lib/categoryProfiles";
import { formatDate } from "../../apps/web/app/lib/dates";
import { expect, test, type Page } from "@playwright/test";

function password(role: "BUYER" | "SELLER" | "ADMIN"): string {
  if (process.env.E2E_TEST_PROJECT !== "r136-fulltest") {
    throw new Error("Запускать только на выделенном синтетическом стенде r136-fulltest.");
  }
  const value = process.env[`E2E_${role}_PASSWORD`];
  if (!value || value.length < 16) {
    throw new Error(`Задайте E2E_${role}_PASSWORD (не менее 16 символов) для отдельного тестового стенда.`);
  }
  return value;
}

function accountEmail(role: "BUYER" | "SELLER" | "ADMIN"): string {
  return process.env[`E2E_${role}_EMAIL`] || ({BUYER:"demo@demo.ru",SELLER:"seller@demo.ru",ADMIN:"admin@demo.ru"})[role];
}

async function login(page: Page, role: "BUYER" | "SELLER" | "ADMIN") {
  page.setDefaultTimeout(15_000);
  await page.goto("/login");
  await page.getByLabel("Электронная почта", { exact: false }).fill(accountEmail(role));
  await page.getByLabel("Пароль", { exact: false }).fill(password(role));
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  if (role !== "ADMIN") {
    const token = await page.evaluate(() => localStorage.getItem("token"));
    const response = await page.request.get("http://localhost:8001/api/v1/auth/me", {headers:{Authorization:`Bearer ${token}`}});
    expect(response.ok()).toBeTruthy();
    const companies = (await response.json()).companies;
    expect(companies.length).toBeGreaterThan(0);
    expect(companies.every((company:{inn:string}) => company.inn.startsWith("000")), "Только синтетические компании; рабочие данные не изменять").toBe(true);
  }
}

// Две независимые сессии и настоящий backend: предложение не является продажей;
// приёмка после отгрузки меняет количество, а себестоимость доступна только продавцу.
const boltSpecification = { unit: "шт", thread: "М8", material: "сталь", product_kind: "болт", diameter_mm: 8, standard: "синтетическая спецификация Б-01", length_mm: 40, strength_class: "8.8" };


async function fillBoltFields(page: Page) {
  for (const [key, value] of Object.entries(boltSpecification)) {
    let index = (await page.locator('.need-property input[aria-label$=": название"]').evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value))).findIndex(name => canonicalCharacteristicKey(name) === key);
    if (index < 0) {
      await page.getByRole("button", {name:"+ Добавить характеристику",exact:true}).click();
      const picker = page.getByLabel("Добавить характеристику категории", {exact:true});
      if (await picker.locator(`option[value="${key}"]`).count()) await picker.selectOption(key);
      else await page.getByRole("button", {name:"Своё поле",exact:true}).click();
      index = await page.locator('.need-property').count() - 1;
      await page.getByLabel(`Характеристика ${index+1}: название`, {exact:true}).fill(key);
    }
    const field = page.getByLabel(new RegExp(`^Характеристика ${index+1}: значение`));
    if (await field.evaluate(element => element.tagName === "SELECT")) await field.selectOption(String(value));
    else await field.fill(String(value));
  }
}

// A real, blank one-page PDF; only synthetic fixture data is uploaded.
function syntheticSpecificationPdf() {
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; }
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 4\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf);
}

async function reviewSyntheticBoltSpecification(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem("token"));
  const headers = { Authorization: `Bearer ${token}` };
  const me = await page.request.get("http://localhost:8001/api/v1/auth/me", { headers });
  expect(me.ok()).toBeTruthy();
  const company = (await me.json()).companies[0];
  expect(company.inn.startsWith("000")).toBeTruthy();
  const uploaded = await page.request.post(`http://localhost:8002/api/v1/companies/${company.id}/documents`, { headers, multipart: {
    name: "Синтетическое заключение по спецификации болта E2E", document_type: "specification_review",
    scope_category: "Строительство", scope_subcategory: "Крепёж",
    file: {name: "synthetic-specification.pdf", mimeType: "application/pdf", buffer: syntheticSpecificationPdf()},
  } });
  expect(uploaded.status(), await uploaded.text()).toBe(201);
  const document = await uploaded.json();
  const editor = await page.request.post("http://localhost:8001/api/v1/auth/login", {data: {email: accountEmail("ADMIN"), password: password("ADMIN")}});
  expect(editor.ok()).toBeTruthy();
  const deadline = new Date(); deadline.setUTCDate(deadline.getUTCDate() + 60);
  const reviewed = await page.request.post(`http://localhost:8002/api/v1/documents/${document.id}/verification`, {
    headers: {Authorization: `Bearer ${(await editor.json()).access_token}`}, data: {
      decision: "verified", scope_category: "Строительство", scope_subcategory: "Крепёж", valid_until: deadline.toISOString().slice(0, 10),
      confirms: Object.fromEntries(Object.entries(boltSpecification).map(([key, value]) => [key, [String(value)]])),
      note: "Проверка только синтетического стенда по указанной спецификации",
    },
  });
  expect(reviewed.ok(), await reviewed.text()).toBeTruthy();
}

async function recordFulfillment(page: Page, action: string, button: string, values: Record<string, string> = {}) {
  await page.getByLabel("Действие", {exact: true}).selectOption(action);
  for (const [name, value] of Object.entries(values)) await page.getByLabel(name, {exact: true}).fill(value);
  await page.getByLabel("Основание, доказательство или номер акта", {exact: true}).fill(`Синтетический акт E2E: ${action}`);
  await expect(page.getByRole("button", {name: button, exact: true})).toBeDisabled();
  await page.getByLabel("Подтверждаю действие, количество и основание от имени компании", {exact: true}).check();
  const recorded = page.waitForResponse(response => response.request().method() === "POST" && /\/deals\/[^/]+\/fulfillment$/.test(new URL(response.url()).pathname));
  await page.getByRole("button", {name: button, exact: true}).click();
  const response = await recorded;
  expect(response.ok(), await response.text()).toBeTruthy();
  await expect(page.getByText("Действие записано. Количества и история обновлены.", {exact: true})).toBeVisible();
}

async function checkSyntheticStock(seller: Page) {
  const token = await seller.evaluate(() => localStorage.getItem("token"));
  const headers = { Authorization: `Bearer ${token}` };
  const me = await seller.request.get("http://localhost:8001/api/v1/auth/me", { headers });
  expect(me.ok()).toBeTruthy();
  const company = (await me.json()).companies[0];
  const response = await seller.request.get(`http://localhost:8002/api/v1/companies/${company.id}/products`, { headers });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  const product = (Array.isArray(body) ? body : body.items).find((item: {name:string}) => item.name === "Болт М8×40, класс 8.8");
  expect(product, "Для маршрута нужен синтетический болт из seed-каталога").toBeTruthy();
  expect(product.stock_units, "Каждый прогон расходует 200 шт. Подготовьте остаток на отдельном стенде; повторный seed его не восстанавливает.").toBeGreaterThanOrEqual(200);
}

for (const mode of ["manual", "classified", "live-ai"] as const) {
const classified = mode === "classified";
test(`${mode === "live-ai" ? "Живая локальная модель" : classified ? "Точная классификация через API" : "Категория и подкатегория из формы"}: заказ → отгрузка → приёмка → прибыль`, async ({ page, browser }) => {
  test.skip(mode === "live-ai" && process.env.RUN_LIVE_CORE_FLOW !== "1", "Для живой модели нужен RUN_LIVE_CORE_FLOW=1 и отдельный синтетический стенд");
  test.setTimeout(mode === "live-ai" ? 600_000 : 180_000);
  const sellerContext = await browser.newContext({ baseURL: process.env.BASE_URL || "http://localhost:3000", recordVideo: mode === "live-ai" ? {dir: test.info().outputPath("seller-video")} : undefined });
  const seller = await sellerContext.newPage();
  try {
    await login(seller, "SELLER");
    await checkSyntheticStock(seller);
    await login(page, "BUYER");
    await expect(page.getByRole("heading", { name: "Личный кабинет", exact: true })).toBeVisible();
    let needUrl: string;
    if (classified) {
      const token = await page.evaluate(() => localStorage.getItem("token"));
      const headers = { Authorization: `Bearer ${token}` };
      const meResponse = await page.request.get("http://localhost:8001/api/v1/auth/me", { headers });
      expect(meResponse.ok()).toBeTruthy();
      const company = (await meResponse.json()).companies.find((item: { membership: { can_buy: boolean } }) => item.membership.can_buy);
      const addressResponse = await page.request.get(`http://localhost:8002/api/v1/companies/${company.id}/addresses`, { headers });
      expect(addressResponse.ok()).toBeTruthy();
      const addresses = await addressResponse.json();
      const deadline = new Date(); deadline.setUTCDate(deadline.getUTCDate() + 30);
      const created = await page.request.post("http://localhost:8002/api/v1/needs", { headers, data: {
        company_id: company.id, category: "Строительство", subcategory: "Крепёж", characteristics: boltSpecification,
        volume_units: 200, budget_rub: 5000, deadline_date: deadline.toISOString().slice(0, 10),
        delivery_address_id: (Array.isArray(addresses) ? addresses : addresses.items)[0].id, visibility: "open_anonymized",
      } });
      expect(created.status()).toBe(201);
      const need = await created.json();
      expect((await page.request.post(`http://localhost:8002/api/v1/needs/${need.id}/publish`, { headers })).ok()).toBeTruthy();
      needUrl = new URL(`/needs/${need.id}`, page.url()).toString();
    } else {
    await page.goto("/needs/new");
    const deadline = new Date(); deadline.setDate(deadline.getDate() + 30);
    const day = `${deadline.getFullYear()}-${String(deadline.getMonth()+1).padStart(2,"0")}-${String(deadline.getDate()).padStart(2,"0")}`;
    if (mode === "live-ai") {
      await page.getByLabel("Что требуется купить", {exact:true}).fill(`Нужно купить 200 болтов М8×40, класс прочности 8.8, материал сталь, диаметр 8 мм, длина 40 мм. Стандарт: синтетическая спецификация Б-01. Единица заказа: шт. Бюджет 5000 рублей. Получить до ${formatDate(day)}. Категория Строительство, Крепёж.`);
      const analysis = page.waitForResponse(response => response.request().method() === "POST" && /\/buyer-agent\/runs$/.test(new URL(response.url()).pathname), {timeout:240_000});
      await page.getByRole("button", {name:"Заполнить с ИИ",exact:true}).click();
      const response = await analysis;
      expect(response.status(), "Живой Gateway должен успешно разобрать запрос; ручной fallback не является прохождением").toBe(201);
      const run = await response.json();
      expect(run.used_route).toBe("local_qwen");
      const review = await completeLiveClarifications(page, run);
      await test.info().attach("Уточнения покупателя", { body: JSON.stringify({
        quantity_extracted_initially: review.quantityExtractedInitially,
        manual_answers: review.manualAnswers,
        note: "Ручные ответы не являются автоматически извлечёнными фактами; это проверка полного маршрута.",
      }, null, 2), contentType: "application/json" });
      await expect(page.getByRole("heading", {name:"Детали закупки",exact:true})).toBeVisible();
      await expect(page.locator("#volume_units")).toHaveValue("200");
      await expect(page.locator("#budget_rub")).toHaveValue("5000");
      await expect(page.locator("#category")).toHaveValue("Строительство");
      await expect(page.locator("#subcategory")).toHaveValue("Крепёж");
    } else {
      await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
      await page.locator("#category").selectOption("Строительство");
      await page.getByLabel("Вид товара", {exact:true}).selectOption("Крепёж");
    }
    // Buyer review is explicit and applies to the extracted or manually entered specification.
    await fillBoltFields(page);
    await page.getByLabel("Количество", { exact: true }).fill("200");
    await page.getByLabel("Бюджет, ₽", { exact: true }).fill("5000");
    await page.getByLabel("Получить до", { exact: true }).fill(formatDate(day));
    const address = page.getByLabel("Адрес доставки", { exact: false });
    await expect(address.locator('option:not([value=""])').first()).toBeAttached();
    await address.selectOption(await address.locator('option:not([value=""])').first().getAttribute("value") as string);
    await page.getByRole("button", { name: "Подтвердить и опубликовать", exact: true }).click();
    await expect(page).toHaveURL(/\/needs\/[0-9a-f-]+/);
    needUrl = page.url();
    }
    const needId = new URL(needUrl).pathname.split("/").at(-1)!;

    await reviewSyntheticBoltSpecification(seller);
    if (classified) {
      // КП готовится API-fixture: отдельный тест проверяет полноту ленты продавца.
      const sellerToken = await seller.evaluate(() => localStorage.getItem("token"));
      const headers = { Authorization: `Bearer ${sellerToken}` };
      const company = (await (await seller.request.get("http://localhost:8001/api/v1/auth/me", { headers })).json()).companies[0];
      const response = await seller.request.get(`http://localhost:8002/api/v1/companies/${company.id}/products`, { headers });
      expect(response.ok()).toBeTruthy();
      const body = await response.json();
      const product = (Array.isArray(body) ? body : body.items).find((item: { name: string }) => item.name === "Болт М8×40, класс 8.8");
      expect((await seller.request.post(`http://localhost:8002/api/v1/needs/${needId}/offers`, { headers, data: {
        company_id: company.id, resource_kind: "stock", product_id: product.id,
        price_rub: 12, available_units: 200, moq_units: 200, delivery_cost_rub: 0, lead_time_days: 2,
        commercial_terms: {delivery_method: "separate", tax_basis: "no_vat", vat_rate_pct: null, delivery_conditions: "Синтетический адрес получателя, Россия", expenses: []},
      } })).status()).toBe(201);
    } else {
    const sellerToken = await seller.evaluate(() => localStorage.getItem("token"));
    const headers = { Authorization: `Bearer ${sellerToken}` };
    const me = await seller.request.get("http://localhost:8001/api/v1/auth/me", { headers });
    expect(me.ok()).toBeTruthy();
    const company = (await me.json()).companies[0];
    const feed = await seller.request.get(`http://localhost:8002/api/v3/needs?seller_company_id=${company.id}`, { headers });
    expect(feed.ok()).toBeTruthy();
    const feedBody = await feed.json();
    const visible = (Array.isArray(feedBody) ? feedBody : feedBody.items).some((need: {id:string}) => need.id === needId);
    if (!visible) {
      const buyerToken = await page.evaluate(() => localStorage.getItem("token"));
      const diagnostic = await page.request.get(`http://localhost:8002/api/v3/needs/${needId}`, {headers:{Authorization:`Bearer ${buyerToken}`}});
      const need = diagnostic.ok() ? await diagnostic.json() : {};
      await test.info().attach("Причина отсутствия в ленте", {contentType:"application/json", body:JSON.stringify({
        need_id:needId, status:need.status, characteristics:need.characteristics, no_match_reason:need.no_match_reason,
        matching_warnings:need.matching_warnings,
      },null,2)});
    }
    expect(visible, "Опубликованная потребность должна быть в ленте продавца. См. характеристики и причину подбора в приложении к отчёту.").toBe(true);
    await seller.goto("/seller/requests");
    const card = seller.locator(`li.demand-card[data-need-id="${needId}"]`);
    await expect(card, "Продавец должен видеть карточку опубликованной потребности").toBeVisible();
    await card.getByRole("button", { name: "Предложить условия", exact: true }).click();
    await seller.locator(`#offer_price_${needId}`).fill("12");
    await seller.locator(`#offer_resource_${needId}`).selectOption("stock");
    await seller.locator(`#offer_product_${needId}`).selectOption({ label: "Болт М8×40, класс 8.8" });
    await seller.locator(`#offer_units_${needId}`).fill("200");
    await seller.locator(`#offer_moq_${needId}`).fill("200");
    await seller.locator(`#offer_lead_${needId}`).fill("2");
    await card.getByRole("combobox", {name: /^Условия доставки/}).selectOption("separate");
    await seller.locator(`#offer_delivery_${needId}`).fill("0");
    await card.getByRole("combobox", {name: /^Налоговая база/}).selectOption("no_vat");
    await card.getByLabel("Условия и место получения", {exact: true}).fill("Синтетический адрес получателя, Россия");
    await card.getByRole("button", { name: "Проверить условия", exact: true }).click();
    await card.getByRole("button", { name: "Подтвердить отправку КП", exact: true }).click();
    await expect(card.getByText("Предложение отправлено. Ожидайте решения покупателя.", { exact: true })).toBeVisible();
    }

    await page.goto(needUrl);
    page.once("dialog", dialog => dialog.accept());
    const selected = page.waitForResponse(r => r.request().method() === "POST" && /\/offers\/[^/]+\/select$/.test(new URL(r.url()).pathname));
    await page.getByRole("button", { name: "Выбрать предложение", exact: true }).click();
    const selectionResponse = await selected;
    expect(selectionResponse.status(), await selectionResponse.text()).toBe(201);
    const dealId = (await selectionResponse.json()).id;
    await expect(page.getByRole("link",{name:"Открыть заказ",exact:true})).toHaveAttribute("href",`/deals?deal=${dealId}`);
    await expect(page.getByRole("heading", { name: "Сделка заключена", exact: true })).toBeVisible();

    await seller.goto("/deals");
    await seller.locator(`[data-deal-id="${dealId}"]`).click();
    await expect(seller.getByText("Операций пока нет. Заказ ещё не считается продажей.", { exact: true })).toBeVisible();
    await recordFulfillment(seller, "prepare", "Сохранить параметры отгрузки", {
      "Адрес отгрузки в России": "г. Москва, ул. Синтетическая, д. 1", "Город": "Москва", "Регион": "Москва",
      "Упаковка": "Коробка", "Вес, кг": "5", "Объём, м³": "0.1", "Количество мест": "1",
    });
    await recordFulfillment(seller, "production", "Начать производство");
    await page.goto("/deals");
    await page.locator(`[data-deal-id="${dealId}"]`).click();
    await recordFulfillment(page, "logistics", "Согласовать получение", {"Подтверждённый тариф, ₽ (0 — без платы)": "0"});
    await seller.reload();
    await seller.locator(`[data-deal-id="${dealId}"]`).click();
    await recordFulfillment(seller, "shipment", "Записать отгрузку", {"Название или номер партии": "Партия E2E", "Количество отгрузки": "200"});
    await page.reload();
    await page.locator(`[data-deal-id="${dealId}"]`).click();
    await page.getByRole("button", {name: "Записать получение", exact: true}).click();
    await recordFulfillment(page, "receipt", "Записать получение партии", {"Фактически получено": "200", "Не поставлено из этой партии": "0"});
    await page.getByRole("button", {name: "Проверить полученное", exact: true}).click();
    await recordFulfillment(page, "inspection", "Сохранить результат проверки", {"Принято после проверки": "200", "Отклонено, требуется решение": "0"});
    const execution = page.locator("section").filter({has: page.getByRole("heading", {name: "Исполнение и расчёты", exact: true})});
    await expect(execution.locator(".stats-grid > div").filter({has: page.getByText("Принято", {exact: true})}).locator("dd")).toHaveText("200");
    await expect(page.getByLabel("Себестоимость единицы, ₽", { exact: true })).toHaveCount(0);

    await seller.reload();
    await seller.locator(`[data-deal-id="${dealId}"]`).click();
    await seller.getByText("Себестоимость и прибыль — только для вашей компании", { exact: true }).click();
    await seller.getByLabel("Себестоимость единицы, ₽", { exact: true }).fill("8");
    await seller.getByLabel("Прочие затраты заказа, ₽", { exact: true }).fill("100");
    await seller.getByLabel("Налоговая база затрат", { exact: true }).selectOption("no_vat");
    await seller.getByLabel("Источник расчёта затрат", { exact: true }).fill("Синтетическая смета E2E");
    await seller.getByLabel("Подтверждаю затраты для расчёта", { exact: false }).check();
    await seller.getByRole("button", { name: "Сохранить затраты", exact: true }).click();
    await expect(seller.getByText(/Валовая прибыль:/)).toContainText(/800\s*₽/);
    await expect(seller.getByText(/После указанных затрат:/)).toContainText(/700\s*₽/);
  } finally {
    await sellerContext.close();
  }
});
}

// Страницы проверяются браузером, без визуального ручного обхода и без подмены API.
for (const role of ["BUYER", "SELLER"] as const) {
  test(`рабочие страницы: ${role}`, async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
      const type = response.request().resourceType();
      if (response.status() >= 500 || (response.status() >= 400 && ["script", "stylesheet", "font", "image"].includes(type))) {
        errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
      }
    });
    await login(page, role);
    const common = ["/dashboard", "/company/new", "/needs", "/catalog", "/deals", "/notifications", "/coalitions", "/resilience", "/kpi", "/knowledge", "/support", "/settings", "/ai-procurement"];
    const routes = role === "SELLER"
      ? [...common, "/seller/profile", "/seller/passport", "/seller/products", "/seller/documents", "/seller/capacity", "/seller/requests", "/seller/opportunities", "/seller/reserves", "/seller/analytics"]
      : [...common, "/needs/new", "/buyer/analytics"];
    for (const route of routes) {
      await test.step(route, async () => {
        const response = await page.goto(route);
        expect(response?.ok()).toBeTruthy();
        await expect(page).toHaveURL(new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
        await expect(page.locator("h1").first()).toBeVisible();
        await page.waitForLoadState("networkidle");
        await expect.soft(page.locator(".alert-error")).toHaveCount(0);
      });
    }
    expect(errors).toEqual([]);
  });
}

test("публичные страницы без авторизации", async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
      const type = response.request().resourceType();
      if (response.status() >= 500 || (response.status() >= 400 && ["script", "stylesheet", "font", "image"].includes(type))) {
        errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
      }
    });
  for (const route of ["/", "/login", "/register", "/catalog", "/info/about", "/info/news", "/info/contacts", "/info/guide", "/info/regulations", "/info/legal", "/info/privacy"]) {
    await test.step(route, async () => {
      expect((await page.goto(route))?.ok()).toBeTruthy();
      await expect(page.locator("h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expect.soft(page.locator(".alert-error")).toHaveCount(0);
    });
  }
  expect(errors).toEqual([]);
});


test("страницы администратора", async ({ page }) => {
  await login(page, "ADMIN");
  await expect(page.getByRole("heading", { name: "Рабочее место администратора", exact: true })).toBeVisible();
  for (const route of ["/admin", "/notifications", "/support", "/settings"]) {
    await test.step(route, async () => {
      expect((await page.goto(route))?.ok()).toBeTruthy();
      await expect(page.locator("h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expect.soft(page.locator(".alert-error")).toHaveCount(0);
    });
  }
});

test("продавец без права покупки не создаёт потребность", async ({ page }) => {
  await login(page, "SELLER");
  await page.goto("/needs/new");
  await expect(page.getByText('У вас нет компании с правом «Покупаю». Создайте компанию и включите режим покупки.', { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Подтвердить и опубликовать", exact: true })).toHaveCount(0);
});

test("карточки каталога, производителя и своей компании", async ({ page }) => {
  await login(page, "BUYER");
  const token = await page.evaluate(() => localStorage.getItem("token"));
  const meResponse = await page.request.get("http://localhost:8001/api/v1/auth/me", { headers: { Authorization: `Bearer ${token}` } });
  expect(meResponse.ok()).toBeTruthy();
  const me = await meResponse.json();
  await page.goto(`/company/${me.companies[0].id}`);
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect.soft(page.locator(".alert-error")).toHaveCount(0);
  await page.goto("/catalog");
  const productLinks = page.locator('a[href^="/catalog/"]');
  await expect(productLinks.first()).toBeVisible();
  const paths = [...new Set(await productLinks.evaluateAll(links => links.map(link => link.getAttribute("href")!)))];
  expect(paths.length).toBeGreaterThan(1);
  for (const path of paths) {
    expect((await page.goto(path))?.ok()).toBeTruthy();
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect.soft(page.locator(".alert-error")).toHaveCount(0);
  }
  const producer = page.locator('a[href^="/producers/"]').first();
  await expect(producer).toBeVisible();
  await producer.click();
  await expect(page.locator("h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect.soft(page.locator(".alert-error")).toHaveCount(0);
});


test("лента продавца содержит подходящую подкатегорию товара", async ({ page }) => {
  await login(page, "SELLER");
  await page.goto("/seller/requests");
  // Создаём новый запрос API в другой сессии, проверяя именно показ ленты.
  const buyerLogin = await page.request.post("http://localhost:8001/api/v1/auth/login", { data: { email: "demo@demo.ru", password: password("BUYER") } });
  expect(buyerLogin.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await buyerLogin.json()).access_token}` };
  const company = (await (await page.request.get("http://localhost:8001/api/v1/auth/me", { headers })).json()).companies[0];
  const deadline = new Date(); deadline.setUTCDate(deadline.getUTCDate() + 30);
  const created = await page.request.post("http://localhost:8002/api/v1/needs", { headers, data: {
    company_id: company.id, category: "Крепёж", characteristics: { unit: "шт", thread: "М8" },
    volume_units: 500, budget_rub: 5000, deadline_date: deadline.toISOString().slice(0, 10), visibility: "open_anonymized",
  } });
  expect(created.status()).toBe(201);
  const need = await created.json();
  expect((await page.request.post(`http://localhost:8002/api/v1/needs/${need.id}/publish`, { headers })).ok()).toBeTruthy();
  await page.reload();
  await expect(page.locator(`li.demand-card[data-need-id="${need.id}"]`)).toHaveCount(1);
});


test("администратор и редактор: компания, обращение, документы, правила и отзыв роли", async ({page, browser}) => {
  test.setTimeout(180_000);
  await login(page, "ADMIN");
  const adminToken = await page.evaluate(() => localStorage.getItem("token"));
  const adminHeaders = {Authorization: `Bearer ${adminToken}`};
  const suffix = crypto.randomUUID(); const email = `review-${suffix}@demo.ru`; const accountPassword = `Access-${suffix}`;
  const registered = await page.request.post("http://localhost:8001/api/v2/auth/register", {data: {rules_version:"rules-2",privacy_version:"privacy-2",rules_accepted: true, privacy_acknowledged: true, last_name: "Проверка", first_name: "Редактора", email, password: accountPassword}});
  expect(registered.status()).toBe(201);
  const account = await registered.json(); const userHeaders = {Authorization: `Bearer ${account.access_token}`};
  const created = await page.request.post("http://localhost:8001/api/v1/companies", {headers: userHeaders, data: {
    full_name: "ООО «Проверка кабинетов»", display_name: `Проверка-${suffix}`, legal_form: "ООО", inn: "0000000000", ogrn: "0000000000000",
    legal_address: "Россия, г. Москва, ул. Синтетическая, д. 1", can_buy: true, can_sell: true,
  }});
  expect(created.status(), await created.text()).toBe(201);
  const company = await created.json();
  expect((await page.request.post(`http://localhost:8001/api/v1/companies/${company.id}/submit-review`, {headers: userHeaders})).ok()).toBeTruthy();
  const subject = `Вопрос-${suffix}`;
  expect((await page.request.post("http://localhost:8002/api/v1/support/tickets", {headers: userHeaders, data: {subject, message: "Уточните порядок проверки нашей компании."}})).status()).toBe(201);
  await page.goto("/admin");
  const companyCard = page.locator("li.card").filter({hasText: company.display_name});
  page.once("dialog", dialog => dialog.accept("Синтетические реквизиты проверены"));
  await companyCard.getByRole("button", {name: "Подтвердить компанию", exact: true}).click();
  await expect(companyCard).toHaveCount(0);
  const ticket = page.locator("li.card").filter({has: page.getByText(subject, {exact: true})});
  await ticket.getByRole("button", {name: "Отправить ответ и закрыть", exact: true}).click();
  await expect(page.getByText("Напишите ответ пользователю перед закрытием обращения.", {exact: true})).toBeVisible();
  await ticket.getByLabel("Ответ", {exact: true}).fill("Компания проверена, можно продолжить работу.");
  await ticket.getByRole("button", {name: "Отправить ответ и закрыть", exact: true}).click();
  await expect(ticket.getByText("Решено", {exact: true})).toBeVisible();
  const member = page.locator(".company-row").filter({has: page.getByText(email, {exact: false})});
  await member.getByLabel("Основание назначения или снятия роли редактора", {exact: true}).fill("Синтетическая проверка полномочий");
  await member.getByRole("button", {name: "Назначить редактором", exact: true}).click();
  await expect(member.getByRole("button", {name: "Снять роль редактора", exact: true})).toBeVisible();
  const editorContext = await browser.newContext({baseURL: process.env.BASE_URL || "http://localhost:3000"});
  try {
    const editor = await editorContext.newPage();
    await editor.goto("/login");
    await editor.getByLabel("Электронная почта", {exact: false}).fill(email);
    await editor.getByLabel("Пароль", {exact: false}).fill(accountPassword);
    await editor.getByRole("button", {name: "Войти", exact: true}).click();
    await expect(editor).toHaveURL(/\/dashboard/);
    await editor.goto("/editor");
    await expect(editor.getByRole("heading", {name: "Кабинет редактора", exact: true})).toBeVisible();
    const token = await editor.evaluate(() => localStorage.getItem("token"));
    const editorHeaders = {Authorization: `Bearer ${token}`};
    expect((await editor.request.get("http://localhost:8001/api/v1/admin/users", {headers: editorHeaders})).status()).toBe(403);
    const documentName = `Спецификация-${suffix}`;
    const upload = await page.request.post(`http://localhost:8002/api/v1/companies/${company.id}/documents`, {headers: userHeaders, multipart: {
      name: documentName, document_type: "specification_review", scope_category: "Строительство", scope_subcategory: "Крепёж",
      file: {name: "synthetic-review.pdf", mimeType: "application/pdf", buffer: syntheticSpecificationPdf()},
    }});
    expect(upload.status(), await upload.text()).toBe(201);
    await editor.reload();
    const document = editor.locator("fieldset").filter({has: editor.getByRole("heading", {name: documentName, exact: true})});
    const downloaded = editor.waitForEvent("download");
    await document.getByRole("button", {name: "Скачать для проверки", exact: true}).click();
    expect((await downloaded).suggestedFilename()).toBe(documentName);
    await document.getByLabel("Подтверждённые характеристики", {exact: true}).fill(Object.entries(boltSpecification).map(([key,value]) => `${key}: ${value}`).join("\n"));
    await document.getByLabel("Заключение", {exact: true}).fill("Применимость синтетической спецификации проверена");
    await document.getByRole("button", {name: "Применимость проверена — подтвердить", exact: true}).click();
    await expect(document).toHaveCount(0);
    await editor.getByRole("combobox", {name: /^Состояние/}).selectOption("verified");
    await expect(document).toBeVisible();
    await document.getByLabel("Подтверждённые характеристики", {exact: true}).fill("Синтаксическая ошибка не мешает отзыву");
    await document.getByLabel("Заключение", {exact: true}).fill("Применимость отозвана после дополнительной проверки");
    await document.getByRole("button", {name: "Отозвать с причиной", exact: true}).click();
    await expect(document).toHaveCount(0);
    await editor.getByRole("combobox", {name: /^Категория/}).selectOption("packaging.paper-cups");
    await editor.getByLabel("Основание изменений", {exact: true}).fill("Уточнены проверки приёмки синтетического стенда");
    await editor.getByLabel("Проверки при приёмке, по одной в строке", {exact: true}).fill("Проверка количества\nПроверка упаковки");
    await editor.getByRole("button", {name: "Проверить изменения", exact: true}).click();
    await expect(editor.getByRole("button", {name: "Опубликовать новую версию", exact: true})).toBeDisabled();
    await editor.getByLabel("Изменения и их предметное основание проверены", {exact: true}).check();
    await editor.getByRole("button", {name: "Опубликовать новую версию", exact: true}).click();
    await expect(editor.getByText("Новая версия правил опубликована.", {exact: true})).toBeVisible();
    await member.getByRole("button", {name: "Снять роль редактора", exact: true}).click();
    await editor.reload();
    await expect(editor.getByRole("main").getByRole("alert")).toContainText(/редактор|доступ|полномоч/);
  } finally {await editorContext.close();}
  expect((await page.request.get(`http://localhost:8001/api/v1/admin/companies?status=verified`, {headers: adminHeaders})).ok()).toBeTruthy();
});
