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

async function login(page: Page, role: "BUYER" | "SELLER" | "ADMIN") {
  page.setDefaultTimeout(15_000);
  await page.goto("/login");
  await page.getByLabel("Электронная почта", { exact: false }).fill(role === "BUYER" ? "demo@demo.ru" : role === "SELLER" ? "seller@demo.ru" : "admin@demo.ru");
  await page.getByLabel("Пароль", { exact: false }).fill(password(role));
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

// Две независимые сессии и настоящий backend: предложение не является продажей;
// приёмка после отгрузки меняет количество, а себестоимость доступна только продавцу.
const boltSpecification = { unit: "шт", thread: "М8", material: "сталь", product_kind: "болт", diameter_mm: 8, standard: "синтетическая спецификация Б-01", length_mm: 40, strength_class: "8.8" };

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
  const editor = await page.request.post("http://localhost:8001/api/v1/auth/login", {data: {email: "admin@demo.ru", password: password("ADMIN")}});
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

for (const classified of [false, true]) {
test(`${classified ? "Точная классификация через API" : "Категория и подкатегория из формы"}: заказ → отгрузка → приёмка → прибыль`, async ({ page, browser }) => {
  test.setTimeout(180_000);
  const sellerContext = await browser.newContext({ baseURL: process.env.BASE_URL || "http://localhost:3000" });
  const seller = await sellerContext.newPage();
  try {
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
        company_id: company.id, category: "Крепёж", characteristics: boltSpecification,
        volume_units: 200, budget_rub: 5000, deadline_date: deadline.toISOString().slice(0, 10),
        delivery_address_id: (Array.isArray(addresses) ? addresses : addresses.items)[0].id, visibility: "open_anonymized",
      } });
      expect(created.status()).toBe(201);
      const need = await created.json();
      expect((await page.request.post(`http://localhost:8002/api/v1/needs/${need.id}/publish`, { headers })).ok()).toBeTruthy();
      needUrl = new URL(`/needs/${need.id}`, page.url()).toString();
    } else {
    await page.goto("/needs/new");
    await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
    await page.locator("#category").selectOption("Строительство");
    await page.getByLabel("Подкатегория", { exact: false }).selectOption("Крепёж");
    for (const [index, [key, value]] of Object.entries(boltSpecification).entries()) {
      if (index >= 2) await page.getByRole("button", { name: "+ Добавить характеристику", exact: true }).click();
      await page.getByLabel(`Характеристика ${index + 1}: название`, { exact: true }).fill(key);
      await page.getByLabel(`Характеристика ${index + 1}: значение`, { exact: true }).fill(String(value));
    }
    await page.getByLabel("Количество единиц заказа", { exact: false }).fill("200");
    await page.getByLabel("Бюджет, ₽", { exact: false }).fill("5000");
    const deadline = new Date();
    deadline.setUTCDate(deadline.getUTCDate() + 30);
    await page.getByLabel("Срок выполнения", { exact: false }).fill(deadline.toISOString().slice(0, 10));
    const address = page.getByLabel("Адрес доставки", { exact: false });
    await expect(address.locator('option:not([value=""])').first()).toBeAttached();
    await address.selectOption(await address.locator('option:not([value=""])').first().getAttribute("value") as string);
    await page.getByRole("button", { name: "Создать и опубликовать", exact: true }).click();
    await expect(page).toHaveURL(/\/needs\/[0-9a-f-]+/);
    needUrl = page.url();
    }
    const needId = new URL(needUrl).pathname.split("/").at(-1)!;

    await login(seller, "SELLER");
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
    await seller.goto("/seller/requests");
    const card = seller.locator(`li.demand-card[data-need-id="${needId}"]`);
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
    await expect(page.getByRole("heading", { name: "Сделка заключена", exact: true })).toBeVisible();

    await seller.goto("/deals");
    await seller.locator(`[data-deal-id="${dealId}"]`).click();
    await expect(seller.getByText("Операций пока нет. Заказ ещё не считается продажей.", { exact: true })).toBeVisible();
    await recordFulfillment(seller, "prepare", "Подготовка", {
      "Адрес отгрузки в России": "г. Москва, ул. Синтетическая, д. 1", "Город": "Москва", "Регион": "Москва",
      "Упаковка": "Коробка", "Вес, кг": "5", "Объём, м³": "0.1", "Количество мест": "1",
    });
    await recordFulfillment(seller, "production", "Производство");
    await page.goto("/deals");
    await page.locator(`[data-deal-id="${dealId}"]`).click();
    await recordFulfillment(page, "logistics", "Получение и тариф", {"Подтверждённый тариф, ₽ (0 — без платы)": "0"});
    await seller.reload();
    await seller.locator(`[data-deal-id="${dealId}"]`).click();
    await recordFulfillment(seller, "shipment", "Отгрузка партии", {"Название или номер партии": "Партия E2E", "Количество отгрузки": "200"});
    await page.reload();
    await page.locator(`[data-deal-id="${dealId}"]`).click();
    await page.getByRole("button", {name: "Записать получение", exact: true}).click();
    await recordFulfillment(page, "receipt", "Получение партии", {"Фактически получено": "200", "Не поставлено из этой партии": "0"});
    await page.getByRole("button", {name: "Проверить полученное", exact: true}).click();
    await recordFulfillment(page, "inspection", "Проверка партии", {"Принято после проверки": "200", "Отклонено, требуется решение": "0"});
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
  await expect(page.getByRole("button", { name: "Создать и опубликовать", exact: true })).toHaveCount(0);
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
