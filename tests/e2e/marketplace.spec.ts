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
  await page.getByLabel("Email", { exact: false }).fill(role === "BUYER" ? "demo@demo.ru" : role === "SELLER" ? "seller@demo.ru" : "admin@demo.ru");
  await page.getByLabel("Пароль", { exact: false }).fill(password(role));
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

// Две независимые сессии и настоящий backend: предложение не является продажей;
// приёмка после отгрузки меняет количество, а себестоимость доступна только продавцу.
for (const classified of [false, true]) {
test(`${classified ? "Точная классификация через API" : "Общая категория из формы"}: заказ → отгрузка → приёмка → прибыль`, async ({ page, browser }) => {
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
        company_id: company.id, category: "Крепёж", characteristics: { unit: "шт", thread: "М8" },
        volume_units: 200, budget_rub: 5000, deadline_date: deadline.toISOString().slice(0, 10),
        delivery_address_id: (Array.isArray(addresses) ? addresses : addresses.items)[0].id, visibility: "open_anonymized",
      } });
      expect(created.status()).toBe(201);
      const need = await created.json();
      expect((await page.request.post(`http://localhost:8002/api/v1/needs/${need.id}/publish`, { headers })).ok()).toBeTruthy();
      needUrl = new URL(`/needs/${need.id}`, page.url()).toString();
    } else {
    await page.goto("/needs/new");
    await page.getByLabel("Категория", { exact: false }).selectOption("Строительство");
    await page.getByLabel("Характеристика 2: название", { exact: true }).fill("thread");
    await page.getByLabel("Характеристика 2: значение", { exact: true }).fill("М8");
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
      } })).status()).toBe(201);
    } else {
    await seller.goto("/seller/requests");
    const card = seller.locator("li.demand-card").filter({ has: seller.getByRole("heading", { name: classified ? "Крепёж" : "Строительство", exact: true }) });
    await card.getByRole("button", { name: "Предложить условия", exact: true }).click();
    await seller.locator(`#offer_price_${needId}`).fill("12");
    await seller.locator(`#offer_resource_${needId}`).selectOption("stock");
    await seller.locator(`#offer_product_${needId}`).selectOption({ label: "Болт М8×40, класс 8.8" });
    await seller.locator(`#offer_units_${needId}`).fill("200");
    await seller.locator(`#offer_moq_${needId}`).fill("200");
    await seller.locator(`#offer_delivery_${needId}`).fill("0");
    await seller.locator(`#offer_lead_${needId}`).fill("2");
    await card.getByRole("button", { name: "Отправить предложение", exact: true }).click();
    await expect(card.getByText("Предложение отправлено. Ожидайте решения покупателя.", { exact: true })).toBeVisible();
    }

    await page.goto(needUrl);
    page.once("dialog", dialog => dialog.accept());
    const selected = page.waitForResponse(r => r.request().method() === "POST" && /\/offers\/[^/]+\/select$/.test(new URL(r.url()).pathname));
    await page.getByRole("button", { name: "Выбрать предложение", exact: true }).click();
    const selectionResponse = await selected;
    expect(selectionResponse.status(), await selectionResponse.text()).toBe(201);
    await expect(page.getByRole("heading", { name: "Сделка заключена", exact: true })).toBeVisible();

    await seller.goto("/deals");
    await expect(seller.locator(".deal-button")).toHaveCount(1);
    await expect(seller.getByText("Операций пока нет. Заказ ещё не считается продажей.", { exact: true })).toBeVisible();
    for (const stage of ["Производство", "Отгрузка"]) {
      const step = seller.locator(".timeline-step").filter({ has: seller.getByText(stage, { exact: true }) });
      await step.getByRole("button", { name: "Подтвердить", exact: true }).click();
      await expect(step).toHaveClass(/done/);
    }
    await page.goto("/deals");
    await expect(page.locator(".deal-button")).toHaveCount(1);
    await page.getByLabel("Количество (доступно 200)", { exact: true }).fill("200");
    await page.getByLabel("Основание или номер акта", { exact: true }).fill("Синтетический акт E2E, принято 200 единиц");
    await expect(page.getByRole("button", { name: "Записать приёмку", exact: true })).toBeDisabled();
    await page.getByLabel("Подтверждаю вид операции и количество", { exact: false }).check();
    await page.getByRole("button", { name: "Записать приёмку", exact: true }).click();
    await expect(page.getByText("Приёмка записана.", { exact: true })).toBeVisible();
    await expect(page.locator(".stats-grid > div").filter({ has: page.getByText("Принято", { exact: true }) }).locator("dd")).toHaveText("200");
    await expect(page.getByLabel("Себестоимость единицы, ₽", { exact: true })).toHaveCount(0);

    await seller.reload();
    await seller.getByText("Себестоимость и прибыль — только для вашей компании", { exact: true }).click();
    await seller.getByLabel("Себестоимость единицы, ₽", { exact: true }).fill("8");
    await seller.getByLabel("Прочие затраты заказа, ₽", { exact: true }).fill("100");
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
  await expect(page.locator("li.demand-card").filter({ has: page.getByRole("heading", { name: "Крепёж", exact: true }) })).toHaveCount(1);
});
