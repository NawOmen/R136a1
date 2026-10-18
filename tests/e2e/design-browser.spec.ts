import { expect, Page, test } from "@playwright/test";

// UI acceptance uses synthetic API responses; it does not certify live services.
const products = [
  { id: "packaging", name: "Коробки для отправки продукции", category: "Упаковка и тара", subcategory: "Коробки", price_rub: "23.125", moq_units: 100, characteristics: { quantity_unit: "шт" }, price_tiers: [], images: [], company_id: "company-seller" },
  { id: "materials", name: "Листовой материал для производства", category: "Сырьё и материалы", subcategory: "Металлы", price_rub: "1280.50", moq_units: 10, characteristics: {}, price_tiers: [], images: [], company_id: "company-seller" },
  { id: "equipment", name: "Рабочий стол для сборки", category: "Оборудование", subcategory: "Производственное", price_rub: "18400.00", moq_units: 1, characteristics: {}, price_tiers: [], images: [], company_id: "company-seller" },
  { id: "business", name: "Комплект рабочей одежды", category: "Товары для бизнеса", subcategory: "Спецодежда", price_rub: "2450.00", moq_units: 20, characteristics: {}, price_tiers: [], images: [], company_id: "company-seller" },
];
async function publicApi(page: Page) {
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/products") ? products : [] }));
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("products lead the first viewport, with persistent themes, exact prices and working search", async ({ page }) => {
  await publicApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.locator(".market-product")).toHaveCount(4);
  const price = await page.locator(".market-product .market-price").first().boundingBox();
  expect(price && price.y + price.height).toBeLessThanOrEqual(900);
  const photo = await page.locator(".market-product__visual").first().boundingBox();
  expect(photo).not.toBeNull();
  expect(photo!.width / photo!.height).toBeCloseTo(1.546, 1);
  expect((await page.locator(".market-product__body").first().boundingBox())!.height).toBeLessThanOrEqual(100);
  expect(await page.locator(".market-product h2").first().evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(15);
  expect(await page.locator(".site-header__logo img").evaluateAll(els => els.every(el => getComputedStyle(el).filter === "none"))).toBe(true);
  await expect(page.getByRole("heading", { name: "Всё для вашего бизнеса" })).toBeVisible();
  await page.getByRole("button", { name: "Включить тёмную тему" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.locator(".site-header__logo img").evaluateAll(els => els.every(el => getComputedStyle(el).filter === "none"))).toBe(true);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Включить светлую тему" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.goto("/catalog");
  await expect(page.locator(".market-product")).toHaveCount(4);
  // Rendering must not round an exact fractional unit price down to kopecks.
  await expect(page.locator(".market-product").first()).toContainText("23,125");
  await page.getByRole("textbox", { name: "Поиск по маркетплейсу", exact: true }).fill("Коробки");
  await page.getByRole("textbox", { name: "Поиск по маркетплейсу", exact: true }).press("Enter");
  await expect(page.locator(".market-product")).toHaveCount(1);
  await expect(page.locator(".market-product").locator(".market-product__link")).toHaveAttribute("href", "/catalog/packaging");
  await page.getByRole("textbox", { name: "Поиск по маркетплейсу", exact: true }).fill("");
  await page.getByRole("textbox", { name: "Поиск по маркетплейсу", exact: true }).press("Enter");
  await expect(page.locator(".market-product")).toHaveCount(4);
  await page.getByRole("button", { name: "Оборудование", exact: true }).click();
  await expect(page.getByRole("button", { name: "Оборудование", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".market-product")).toHaveCount(1);
  await noOverflow(page);
});

test("catalogue failure can be retried from home without inventing a successful result", async ({ page }) => {
  let failed = true;
  await page.route("**/api/**", route => failed ? route.fulfill({ status: 503, json: { detail: "Временно недоступно" } }) : route.fulfill({ json: products }));
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось загрузить предложения" })).toBeVisible();
  await expect(page.locator(".market-product")).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(4);
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось загрузить предложения" })).toHaveCount(0);
});

test("home and catalogue preserve server popularity through category and name sorting", async ({ page }) => {
  const assortment = [products[3], products[2], { ...products[0], id: "first" }, { ...products[0], id: "another-box" }];
  const requestedSorts: (string | null)[] = [];
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/products")) requestedSorts.push(url.searchParams.get("sort"));
    return route.fulfill({ json: url.pathname.endsWith("/products") ? assortment : [] });
  });
  const links = page.locator(".market-product__link");
  for (const path of ["/", "/catalog"]) {
    await page.goto(path);
    const sort = page.getByRole("combobox", { name: "Порядок товаров" });
    await expect(sort).toHaveValue("popular");
    await expect(sort.locator("option:checked")).toHaveText("По популярности");
    await expect(links).toHaveCount(4);
    expect(await links.evaluateAll(items => items.map(item => item.getAttribute("href")))).toEqual(assortment.map(p => `/catalog/${p.id}`));
    await sort.selectOption("name");
    await expect(links.first()).toHaveAttribute("href", "/catalog/business");
    await sort.selectOption("popular");
    await expect(links.nth(1)).toHaveAttribute("href", "/catalog/equipment");
    await page.getByRole("button", { name: "Упаковка и тара", exact: true }).click();
    await expect(links).toHaveCount(2);
    await expect(links.first()).toHaveAttribute("href", "/catalog/first");
    await expect(links.nth(1)).toHaveAttribute("href", "/catalog/another-box");
  }
  expect(requestedSorts).toEqual(["popular", "popular"]);
});

test("the catalogue keeps supplier photos first and reveals the remaining products", async ({ page }) => {
  const assortment = Array.from({ length: 30 }, (_, index) => ({ ...products[index % products.length], id: `item-${index}`, images: index === 0 ? [{ id: "generated-photo", file_name: "Иллюстрация товара: Коробка.webp", content_type: "image/webp", position: 0 }, { id: "supplier-photo", file_name: "Фото товара.png", content_type: "image/png", position: 1 }] : [] }));
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/products") ? assortment : [] }));
  await page.goto("/");
  await expect(page.locator(".market-product")).toHaveCount(4);
  await expect(page.locator(".market-product").first().locator("img")).toHaveAttribute("src", /product-images\/supplier-photo$/);
  await expect(page.locator(".market-product").first().locator(".product-no-photo")).toHaveCount(0);
  await page.getByRole("button", { name: /Показать ещё/ }).click();
  await expect(page.locator(".market-product")).toHaveCount(28);
  await page.getByRole("button", { name: /Показать ещё/ }).click();
  await expect(page.locator(".market-product")).toHaveCount(30);
  await page.getByRole("button", { name: "Оборудование", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(7);
  await expect(page.getByRole("button", { name: /Показать ещё/ })).toHaveCount(0);
});

test("mobile market, keyboard navigation and reduced motion at 320, 390 and 768 pixels", async ({ page }) => {
  await publicApi(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    await expect(page.locator(".market-product")).toHaveCount(4);
    await expect(page.locator(".market-product").last()).toBeVisible();
    const photo = await page.locator(".market-product__visual").first().boundingBox();
    expect(photo!.width / photo!.height).toBeCloseTo(width < 760 ? 1.2 : 1.546, 1);
    expect((await page.locator(".market-product__body").first().boundingBox())!.height).toBeLessThanOrEqual(width < 760 ? 120 : 100);
    await noOverflow(page);
    const menu = page.getByRole("button", { name: "Открыть навигацию", exact: true });
    await menu.click();
    await expect(page.getByRole("navigation", { name: "Навигация по сайту", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(menu).toBeFocused();
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(await page.locator(".market-product").first().evaluate(el => getComputedStyle(el).transitionDuration)).toBe("0s");
    await page.mouse.move(width - 10, 20);
    expect(await page.locator(".liquid-atmosphere").evaluate(el => getComputedStyle(el).transform)).toBe("none");
    await page.goto("/login");
    await expect(page.getByLabel("Email", { exact: false })).toBeVisible();
    await noOverflow(page);
    await page.goto("/catalog");
    await expect(page.locator(".market-product")).toHaveCount(4);
    expect((await page.locator(".market-search").boundingBox())?.height).toBeGreaterThanOrEqual(44);
    expect((await page.getByRole("textbox", { name: "Поиск по маркетплейсу", exact: true }).boundingBox())?.height).toBeGreaterThanOrEqual(44);
    await noOverflow(page);
  }
});

test("account sheet covers the viewport, keeps keyboard focus and restores scrolling", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-design-user"));
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/auth/me") ? { user: { id: "user-design", first_name: "Анна", last_name: "Соколова", email: "buyer@example.test", is_marketplace_admin: false }, companies: [] } : [] }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/catalog");
  const trigger = page.getByRole("button", { name: "Открыть личный кабинет", exact: true });
  await trigger.click();
  const sheet = page.getByRole("dialog", { name: "Меню аккаунта" });
  await expect(sheet).toBeVisible();
  const box = await sheet.boundingBox();
  expect(box?.y).toBe(0);
  expect(box?.height).toBe(844);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
  const close = sheet.getByRole("button", { name: "Закрыть", exact: true });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(sheet.getByRole("button", { name: "Выйти", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
});

test("home and catalogue retain truthful ordering and keyboard selection", async ({ page }) => {
  await publicApi(page);
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Порядок товаров" })).toHaveValue("popular");
  await page.goto("/catalog");
  const sort = page.getByRole("combobox", { name: "Порядок товаров" });
  await sort.focus();
  await page.keyboard.press("Space");
  await expect(sort).toHaveJSProperty("value", "popular");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(sort).toHaveValue("name");
  await expect(page.locator(".market-product").first().locator(".market-product__link")).toHaveAttribute("href", "/catalog/business");
  await sort.focus();
  await page.keyboard.press("Space");
  await page.keyboard.press("Escape");
  await expect(sort).toBeFocused();
});

test("dark mode changes the atmospheric scene, search and reading surfaces together", async ({ page }) => {
  await publicApi(page);
  await page.addInitScript(() => { if (!localStorage.getItem("porukam-theme")) localStorage.setItem("porukam-theme", "light"); });
  await page.goto("/");
  const surfaces = () => page.evaluate(() => ({
    scene: getComputedStyle(document.querySelector(".liquid-atmosphere")!).backgroundColor,
    ground: getComputedStyle(document.body).backgroundColor,
    search: getComputedStyle(document.querySelector(".market-search")!).backgroundColor,
    reading: getComputedStyle(document.querySelector(".market-product")!).color,
  }));
  await expect(page.locator(".market-product")).toHaveCount(4);
  const light = await surfaces();
  await page.getByRole("button", { name: "Включить тёмную тему" }).click();
  const dark = await surfaces();
  for (const key of ["scene", "ground", "search", "reading"] as const) expect(dark[key]).not.toBe(light[key]);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".market-product")).toHaveCount(4);
  expect(await surfaces()).toEqual(dark);
});

test("the atmosphere remains static when the pointer moves", async ({ page }) => {
  await publicApi(page);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await expect(page.locator(".liquid-atmosphere canvas")).toHaveCount(0);
  const scene = () => page.locator(".liquid-atmosphere").evaluate(el => ({
    transform: getComputedStyle(el,"::before").transform,
    background: getComputedStyle(el,"::before").backgroundImage,
    style: el.getAttribute("style"),
  }));
  const before = await scene();
  await page.mouse.move(400,300); await page.mouse.move(800,200);
  expect(await scene()).toEqual(before);
  expect(before.transform).toBe("none");
});


test("favorites persist locally without swallowing product navigation", async ({ page }) => {
  await publicApi(page);
  await page.goto("/");
  const favorite = page.getByRole("button", { name: "В избранное: Коробки для отправки продукции", exact: true });
  await favorite.click();
  await expect(page).toHaveURL(/\/$/);
  const saved = page.getByRole("button", { name: "Убрать из избранного: Коробки для отправки продукции", exact: true });
  await expect(saved).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(saved).toHaveAttribute("aria-pressed", "true");
  await saved.click();
  await expect(favorite).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator('.market-product__link[href="/catalog/packaging"]')).toBeVisible();
});


test("toggle hover grows gently, returns smoothly and respects reduced motion and disabled states", async ({ page }) => {
  await publicApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await expect(page.locator(".market-product")).toHaveCount(4);
  const selectors = [".market-lanes a", ".storefront-mode a", ".theme-toggle", ".product-favorite", ".catalog-sort select", ".catalog-categories button"];
  const scale = (selector: string) => page.locator(selector).first().evaluate(el => {
    const transform = getComputedStyle(el).transform;
    return transform === "none" ? 1 : new DOMMatrixReadOnly(transform).a;
  });
  for (const selector of selectors) {
    await page.locator(selector).first().hover();
    await expect.poll(() => scale(selector)).toBeCloseTo(1.025, 3);
    await page.mouse.move(5, 250);
    await expect.poll(() => scale(selector)).toBeCloseTo(1, 3);
  }
  await noOverflow(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const selector of selectors) {
    await page.locator(selector).first().hover();
    expect(await scale(selector)).toBe(1);
  }
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-toggle-test"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/next-step")) return route.fulfill({ json: { title: "Выберите товары", description: "Начните закупку", href: "/catalog" } });
    if (path.endsWith("/buyer-savings")) return route.fulfill({ json: { confirmed_savings_rub: "0", calculated_variants_rub: "0", coalitions_count: 0, explanation: "Закупок пока нет." } });
    return route.fulfill({ json: path.endsWith("/auth/me") ? {
      user: { id: "toggle-user", first_name: "Анна", last_name: "Соколова", email: "buyer@example.test", account_status: "active" },
      companies: [{ id: "toggle-company", display_name: "Синтетическая компания", verification_status: "verified", membership: { can_buy: true, can_sell: false, is_admin: true } }]
    } : [] });
  });
  await page.goto("/dashboard");
  const sell = page.getByRole("button", { name: "Продаю", exact: true });
  await expect(sell).toBeDisabled();
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await sell.hover({ force: true });
  expect(await sell.evaluate(el => getComputedStyle(el).transform)).toBe("none");
  await expect(page.getByRole("button", { name: "Покупаю", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.goto("/settings");
  const dark = page.getByRole("button", { name: "☾ Тёмная", exact: true });
  await dark.hover();
  await expect.poll(() => scale(".theme-choice button:last-child")).toBeCloseTo(1.025, 3);
  await dark.click();
  await expect(dark).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(dark).toHaveAttribute("aria-pressed", "true");
});
