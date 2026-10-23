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
async function compactProductBody(page: Page, heightLimit: number) {
  const body = page.locator(".market-product__body").first();
  const minimumOrder = body.locator(".product-conditions");
  await expect(minimumOrder).toHaveText("От 100 шт.");
  await expect(minimumOrder).toBeVisible();
  const minimumOrderHeight = (await minimumOrder.boundingBox())!.height;
  // MOQ remains readable; the full body budget includes a two-line title
  // and the verification label at narrow card widths.
  expect(minimumOrderHeight).toBeLessThanOrEqual(18);
  expect((await body.boundingBox())!.height).toBeLessThanOrEqual(heightLimit);
}

function filterProducts() {
  const fresh = new Date(Date.now() - 60_000).toISOString();
  const base = { ...products[0], characteristics: { unit: "piece" }, stock_units: 50, stock_updated_at: fresh, lead_time_days: 9 };
  return [
    { ...base, id: "price-high", name: "Гамма — коробка", price_rub: "1.000000000002", moq_units: 3 },
    { ...base, id: "price-low", name: "Бета — коробка", price_rub: "1.000000000001", moq_units: 20, lead_time_days: 2 },
    { ...base, id: "price-tier", name: "Альфа — коробка", price_rub: "9", moq_units: 10, lead_time_days: 4, price_tiers: [{ min_units: 100, unit_price_rub: "0.999999999999" }] },
  ];
}

async function fixtureCatalog(page: Page, assortment: object[]) {
  const requestedSorts: (string | null)[] = [];
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/products")) requestedSorts.push(url.searchParams.get("sort"));
    return route.fulfill({ json: url.pathname.endsWith("/products") ? assortment : [] });
  });
  return requestedSorts;
}

async function openCatalogFilters(page: Page) {
  const filters = page.locator("details.catalog-filters");
  if (!(await filters.evaluate(element => (element as HTMLDetailsElement).open))) await filters.locator("summary").click();
  await expect(page.locator(".catalog-filter-form")).toBeVisible();
}

async function productLinks(page: Page) {
  return page.locator(".market-product__link").evaluateAll(items => items.map(item => item.getAttribute("href")));
}

for (const [width, columns] of [[320, 2], [360, 2], [390, 2], [430, 2], [740, 2], [768, 3], [1024, 5], [1280, 5], [1440, 5]]) {
  test(`catalogue has ${columns} readable cards per row at ${width}px`, async ({ page }) => {
    const assortment = Array.from({ length: 12 }, (_, index) => ({ ...products[index % products.length], id: `layout-${index}` }));
    await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/products") ? assortment : [] }));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.locator(".market-product")).toHaveCount(10);
    const cards = await page.locator(".market-product").evaluateAll(items => items.map(item => {
      const box = item.getBoundingClientRect();
      return { top: box.top, width: box.width };
    }));
    expect(cards.filter(card => Math.abs(card.top - cards[0].top) < 1)).toHaveLength(columns);
    expect(cards[columns].top).toBeGreaterThan(cards[0].top);
    expect(cards.every(card => card.width >= 135)).toBe(true);
    await compactProductBody(page, width <= 760 ? 155 : 150);
    const favorite = page.locator(".product-favorite").first();
    const target = (await favorite.boundingBox())!;
    expect(target.width).toBeGreaterThanOrEqual(44);
    expect(target.height).toBeGreaterThanOrEqual(44);
    await noOverflow(page);
  });
}

test("section instructions are absent from the shared page layout", async ({ page }) => {
  await publicApi(page);
  for (const path of ["/catalog", "/login", "/knowledge", "/ai-procurement"]) {
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByText("Как работать с этим разделом", { exact: true })).toHaveCount(0);
  }
});

test.describe("phone landscape", () => {
  test.use({ hasTouch: true, isMobile: true });
  for (const width of [844, 932]) {
    test(`still has two product columns at ${width}px`, async ({ page }) => {
      await publicApi(page);
      await page.setViewportSize({ width, height: 390 });
      await page.goto("/catalog");
      await expect(page.locator(".market-product")).toHaveCount(4);
      const tops = await page.locator(".market-product").evaluateAll(items => items.map(item => item.getBoundingClientRect().top));
      expect(tops[1]).toBe(tops[0]);
      expect(tops[2]).toBeGreaterThan(tops[0]);
      expect((await page.locator(".market-product__visual").first().boundingBox())!.height).toBeLessThanOrEqual(180);
      await noOverflow(page);
    });
  }
});

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
  await compactProductBody(page, 150);
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
  await expect(page.getByRole("status").filter({ hasText: "1 предложение" })).toHaveCount(1);
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
    if (path === "/") {
      await expect(links).toHaveCount(4);
      expect(await links.evaluateAll(items => items.map(item => item.getAttribute("href")))).toEqual(assortment.map(p => `/catalog/${p.id}`));
      continue;
    }
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

test("catalogue sorts exact advertised prices and tier prices without changing the server request", async ({ page }) => {
  const requestedSorts = await fixtureCatalog(page, filterProducts());
  await page.goto("/catalog");
  const sort = page.getByRole("combobox", { name: "Порядок товаров" });
  await expect(page.locator(".market-product")).toHaveCount(3);
  expect(await productLinks(page)).toEqual(["/catalog/price-high", "/catalog/price-low", "/catalog/price-tier"]);
  for (const [value, expected] of [
    ["price-asc", ["price-tier", "price-low", "price-high"]],
    ["price-desc", ["price-high", "price-low", "price-tier"]],
    ["lead-time", ["price-low", "price-tier", "price-high"]],
    ["moq", ["price-high", "price-tier", "price-low"]],
    ["name", ["price-tier", "price-low", "price-high"]],
    ["popular", ["price-high", "price-low", "price-tier"]],
  ] as const) {
    await sort.selectOption(value);
    expect(await productLinks(page)).toEqual(expected.map(id => `/catalog/${id}`));
  }
  await expect(page.locator('.market-product__link[href="/catalog/price-tier"] .product-pricing')).toHaveAttribute("title", /0,999999999999.*100/);
  await openCatalogFilters(page);
  await page.getByLabel("Цена от, ₽", { exact: true }).fill("1,000000000002");
  await page.getByLabel("Цена до, ₽", { exact: true }).fill("1,000000000002");
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  expect(await productLinks(page)).toEqual(["/catalog/price-high"]);
  await openCatalogFilters(page);
  await page.getByLabel("Цена от, ₽", { exact: true }).fill("0.999999999999");
  await page.getByLabel("Цена до, ₽", { exact: true }).fill("0.999999999999");
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  expect(await productLinks(page)).toEqual(["/catalog/price-tier"]);
  expect(requestedSorts).toEqual(["popular"]);
});

test("catalogue combines supplied fields and restores results when filters are cleared", async ({ page }) => {
  const assortment = [...filterProducts(), { ...filterProducts()[0], id: "other-unit", subcategory: "Пакеты", characteristics: { unit: "kg" } }];
  await fixtureCatalog(page, assortment);
  await page.goto("/catalog");
  await expect(page.locator(".market-product")).toHaveCount(4);
  await openCatalogFilters(page);
  await page.getByLabel("Цена от, ₽", { exact: true }).fill("1");
  await page.getByLabel("Цена до, ₽", { exact: true }).fill("2");
  await page.getByLabel("Только в наличии", { exact: true }).check();
  await page.getByLabel("Срок производства, до дней", { exact: true }).fill("9");
  await page.getByLabel("Минимальный заказ, до единиц", { exact: true }).fill("3");
  await page.getByLabel("Подкатегория", { exact: true }).selectOption({ label: "Коробки" });
  await page.getByLabel("Единица заказа", { exact: true }).selectOption({ label: "шт." });
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  expect(await productLinks(page)).toEqual(["/catalog/price-high"]);
  await expect(page.locator("details.catalog-filters summary")).toContainText(/Фильтры.*[1-9]/);
  await openCatalogFilters(page);
  await page.getByRole("button", { name: "Очистить фильтры", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(4);
  await expect(page.getByLabel("Цена от, ₽", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Цена до, ₽", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Только в наличии", { exact: true })).not.toBeChecked();
  await expect(page.locator(".catalog-filter-form [role=alert]")).toHaveCount(0);
});

test("catalogue identifies the actual producer of matching products and reuses each company lookup", async ({ page }) => {
  const [base] = filterProducts();
  const assortment = [
    { ...base, id: "box-alpha", name: "Коробка для отгрузки 400×300×200 мм", company_id: "producer-alpha", price_rub: "20" },
    { ...base, id: "box-beta", name: "Коробка для отгрузки 400×300×200 мм", company_id: "producer-beta", price_rub: "21", stock_units: 0 },
    { ...base, id: "stale-alpha", company_id: "producer-alpha", stock_units: 0, stock_updated_at: new Date(Date.now() - 8 * 86_400_000).toISOString() },
    { ...base, id: "fresh-beta", company_id: "producer-beta" },
  ];
  const names: Record<string, string> = { "producer-alpha": "ООО «Упаковка Альфа»", "producer-beta": "ООО «Упаковка Бета»" };
  const lookups: string[] = [];
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    const company = path.match(/\/producers\/([^/]+)$/)?.[1];
    if (company) { lookups.push(company); return route.fulfill({ json: { company_id: company, display_name: names[company] } }); }
    return route.fulfill({ json: path.endsWith("/products") ? assortment : [] });
  });
  await page.goto("/catalog");
  await expect(page.locator(".market-product")).toHaveCount(4);
  for (const product of assortment) {
    const producer = page.locator(`.market-product__link[href="/catalog/${product.id}"] .manufacturer-status`);
    await expect(producer).toHaveText(names[product.company_id]);
    await expect(producer).toHaveAttribute("title", `Проверенный производитель: ${names[product.company_id]}`);
  }
  const unavailable = page.locator('.market-product__link[href="/catalog/box-beta"] .product-stock');
  await expect(unavailable).toHaveText("Нет в наличии");
  await expect(unavailable.locator("svg")).toHaveCount(1);
  const stale = page.locator('.market-product__link[href="/catalog/stale-alpha"] .product-stock');
  await expect(stale).toHaveText("Уточнить наличие");
  await expect(stale.locator("svg")).toHaveCount(0);
  await page.getByRole("combobox", { name: "Порядок товаров" }).selectOption("price-asc");
  await page.getByRole("button", { name: "Упаковка и тара", exact: true }).click();
  await openCatalogFilters(page);
  await page.getByLabel("Только в наличии", { exact: true }).check();
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  expect(await productLinks(page)).toEqual(["/catalog/fresh-beta", "/catalog/box-alpha"]);
  await openCatalogFilters(page);
  await page.getByRole("button", { name: "Очистить фильтры", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(4);
  await expect(page.locator(".manufacturer-status").filter({ hasText: names["producer-alpha"] })).toHaveCount(2);
  await expect(page.locator(".manufacturer-status").filter({ hasText: names["producer-beta"] })).toHaveCount(2);
  expect(lookups.sort()).toEqual(["producer-alpha", "producer-beta"]);
});

test("producer lookup failures and mismatched responses preserve the truthful catalogue fallback", async ({ page }) => {
  const [base] = filterProducts();
  const assortment = [
    { ...base, id: "lookup-failed", company_id: "producer-failed" },
    { ...base, id: "lookup-mismatched", company_id: "producer-mismatched" },
    { ...base, id: "lookup-empty", company_id: "producer-empty" },
  ];
  const lookups: string[] = [];
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    const company = path.match(/\/producers\/([^/]+)$/)?.[1];
    if (company) {
      lookups.push(company);
      if (company === "producer-failed") return route.fulfill({ status: 503, json: { detail: "Сведения временно недоступны" } });
      return route.fulfill({ json: company === "producer-mismatched" ? { company_id: "another-company", display_name: "Другая компания" } : { company_id: company, display_name: "   " } });
    }
    return route.fulfill({ json: path.endsWith("/products") ? assortment : [] });
  });
  await page.goto("/catalog");
  await expect.poll(() => lookups.length).toBe(3);
  await expect(page.locator(".market-product")).toHaveCount(3);
  await expect(page.locator(".manufacturer-status").filter({ hasText: "Проверенный производитель" })).toHaveCount(3);
  await expect(page.getByText("Другая компания", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось загрузить предложения" })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Порядок товаров" }).selectOption("name");
  await openCatalogFilters(page);
  await page.getByLabel("Только в наличии", { exact: true }).check();
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(3);
  await page.getByRole("button", { name: "Очистить фильтры", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(3);
  await expect(page.locator(".manufacturer-status").filter({ hasText: "Проверенный производитель" })).toHaveCount(3);
  await expect(page.getByText("Другая компания", { exact: true })).toHaveCount(0);
  expect(lookups.sort()).toEqual(["producer-empty", "producer-failed", "producer-mismatched"]);
});

test("catalogue rejects invalid money and reversed ranges without applying a partial filter", async ({ page }) => {
  await fixtureCatalog(page, filterProducts());
  await page.goto("/catalog");
  await expect(page.locator(".market-product")).toHaveCount(3);
  await openCatalogFilters(page);
  const from = page.getByLabel("Цена от, ₽", { exact: true });
  const to = page.getByLabel("Цена до, ₽", { exact: true });
  const submit = page.getByRole("button", { name: "Применить фильтры", exact: true });
  for (const [minimum, maximum] of [["-1", ""], ["цена", ""], ["0.1234567890123", ""], ["2", "1"]]) {
    await from.fill(minimum);
    await to.fill(maximum);
    await submit.click();
    await expect(page.locator(".catalog-filter-form [role=alert]")).toBeVisible();
    await expect(page.locator(".market-product")).toHaveCount(3);
    expect(new URL(page.url()).searchParams.has("price_from")).toBe(false);
  }
  await from.fill(""); await to.fill("");
  for (const [label, value] of [["Срок производства, до дней", "-1"], ["Минимальный заказ, до единиц", "заказ"]]) {
    const field = page.getByLabel(label, { exact: true });
    await field.fill(value);
    await submit.click();
    await expect(page.locator(".catalog-filter-form [role=alert]")).toBeVisible();
    await expect(page.locator(".market-product")).toHaveCount(3);
    await field.fill("");
  }
  await from.fill("100");
  await submit.click();
  await expect(page.locator(".catalog-filter-form [role=alert]")).toHaveCount(0);
  await expect(page.locator(".market-product")).toHaveCount(0);
  await expect(page.getByText("Подходящих товаров пока нет", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Очистить фильтры", exact: true }).first().click();
  await expect(page.locator(".market-product")).toHaveCount(3);
});

test("availability requires fresh seller stock and numeric limits exclude unknown facts", async ({ page }) => {
  const [base] = filterProducts();
  const assortment = [
    { ...base, id: "fresh-stock", lead_time_days: 2, moq_units: 2 },
    { ...base, id: "near-future-stock", stock_updated_at: new Date(Date.now() + 30_000).toISOString(), lead_time_days: 2, moq_units: 2 },
    { ...base, id: "stale-stock", stock_updated_at: new Date(Date.now() - 8 * 86_400_000).toISOString() },
    { ...base, id: "far-future-stock", stock_updated_at: new Date(Date.now() + 120_000).toISOString() },
    { ...base, id: "missing-time", stock_updated_at: null },
    { ...base, id: "missing-stock", stock_units: null },
    { ...base, id: "zero-stock", stock_units: 0 },
    { ...base, id: "missing-lead", lead_time_days: null, moq_units: 2 },
    { ...base, id: "missing-moq", lead_time_days: 2, moq_units: null },
  ];
  await fixtureCatalog(page, assortment);
  await page.goto("/catalog");
  await expect(page.locator(".market-product")).toHaveCount(9);
  await openCatalogFilters(page);
  await page.getByLabel("Только в наличии", { exact: true }).check();
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  expect(await productLinks(page)).toEqual(["/catalog/fresh-stock", "/catalog/near-future-stock", "/catalog/missing-lead", "/catalog/missing-moq"]);
  await openCatalogFilters(page);
  await page.getByLabel("Срок производства, до дней", { exact: true }).fill("3");
  await page.getByLabel("Минимальный заказ, до единиц", { exact: true }).fill("2");
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  expect(await productLinks(page)).toEqual(["/catalog/fresh-stock", "/catalog/near-future-stock"]);
});

test("catalogue URL retains search, filters and sort across reload and Back", async ({ page }) => {
  await fixtureCatalog(page, filterProducts());
  await page.goto("/catalog?q=коробка");
  await expect(page.locator(".market-product")).toHaveCount(3);
  const sort = page.getByRole("combobox", { name: "Порядок товаров" });
  await sort.selectOption("price-asc");
  await openCatalogFilters(page);
  const unchangedUrl = page.url();
  await page.getByLabel("Цена до, ₽", { exact: true }).fill("1,000000000001");
  expect(page.url()).toBe(unchangedUrl);
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  expect(await productLinks(page)).toEqual(["/catalog/price-tier", "/catalog/price-low"]);
  expect(new URL(page.url()).searchParams.get("q")).toBe("коробка");
  expect(new URL(page.url()).searchParams.get("sort")).toBe("price-asc");
  await page.reload();
  await expect(page.locator(".market-product")).toHaveCount(2);
  await expect(sort).toHaveValue("price-asc");
  await openCatalogFilters(page);
  await expect(page.getByLabel("Цена до, ₽", { exact: true })).toHaveValue(/1[.,]000000000001/);
  await page.getByRole("button", { name: "Очистить фильтры", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(3);
  expect(new URL(page.url()).searchParams.get("q")).toBe("коробка");
  await page.goBack();
  await expect(page.locator(".market-product")).toHaveCount(2);
  await expect(sort).toHaveValue("price-asc");
});

test.describe("catalogue filter layout on phones", () => {
  test.use({ hasTouch: true, isMobile: true });
  for (const theme of ["light", "dark"]) {
    for (const [width, height] of [[320, 844], [390, 844], [844, 390]]) {
      test(`filters remain operable with two product columns at ${width}px in ${theme}`, async ({ page }) => {
        await page.addInitScript(value => localStorage.setItem("porukam-theme", value), theme);
        await fixtureCatalog(page, filterProducts());
        await page.setViewportSize({ width, height });
        await page.goto("/catalog");
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.locator(".market-product")).toHaveCount(3);
        const filters = page.locator("details.catalog-filters");
        expect(await filters.evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
        const summary = filters.locator("summary");
        expect((await summary.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await summary.click();
        await expect(page.locator(".catalog-filter-form")).toBeVisible();
        const targetHeights = await page.locator('.catalog-filter-form input:not([type="checkbox"]), .catalog-filter-form select, .catalog-filter-form button').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height));
        expect(targetHeights.every(value => value >= 44)).toBe(true);
        await noOverflow(page);
        await page.getByLabel("Цена от, ₽", { exact: true }).fill("0,5");
        await page.getByLabel("Минимальный заказ, до единиц", { exact: true }).fill("30");
        await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
        await expect(page.locator(".market-product")).toHaveCount(3);
        await expect(summary).toContainText(/Фильтры.*[1-9]/);
        if (await filters.evaluate(element => (element as HTMLDetailsElement).open)) await summary.click();
        expect(await filters.evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
        const tops = await page.locator(".market-product").evaluateAll(elements => elements.map(element => element.getBoundingClientRect().top));
        expect(tops[1]).toBe(tops[0]);
        expect(tops[2]).toBeGreaterThan(tops[0]);
        await noOverflow(page);
      });
    }
  }
});

for (const theme of ["light", "dark"]) {
  for (const width of [320, 390, 1440]) {
    test(`product stock and origin badges do not overlap at ${width}px in ${theme}`, async ({ page }) => {
      await page.addInitScript(value => localStorage.setItem("porukam-theme", value), theme);
      await page.setViewportSize({ width, height: 1000 });
      const detail = {
        ...filterProducts()[0], id: "apron", name: "Фартук хлопковый 80×90 см", category: "Товары для бизнеса", subcategory: "Спецодежда", price_rub: "650", moq_units: 20,
        images: [{ id: "synthetic-apron-photo", file_name: "Иллюстрация товара: Фартук.webp", content_type: "image/webp", position: 0 }],
        producer: { company_id: "company-seller", display_name: "Производитель рабочей одежды", legal_form: "ООО", region: "Новосибирская область", about: null, production_site_address: null, has_photo: false, rating: null, reviews_count: 0 },
      };
      await page.route("**/api/**", route => {
        const path = new URL(route.request().url()).pathname;
        if (path.includes("/product-images/")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600"><rect width="600" height="600" fill="#f5f5f2"/></svg>' });
        if (path.endsWith("/detail")) return route.fulfill({ json: detail });
        if (path.endsWith("/admission")) return route.fulfill({ json: { product_id: "apron", category: detail.category, subcategory: detail.subcategory, state: "admitted", state_label: "Проверено человеком", supported: true, summary: "Проверено человеком", checklist: [{ code: "specification", title: "Спецификация товара", state: "satisfied", state_label: "Проверено человеком", legal_reference: "Требования к спецификации", buyer_note: "Сведения подтверждены" }], advisories: [], note: "Проверено человеком", checked_at: new Date().toISOString() } });
        return route.fulfill({ json: [] });
      });
      await page.goto("/catalog/apron");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const gallery = page.locator(".product-gallery");
      await expect(gallery.locator("img")).toHaveAttribute("alt", "Фартук хлопковый 80×90 см");
      await expect(gallery.locator(".product-image-note")).toHaveCount(0);
      const stock = gallery.locator(".product-stock");
      const origin = gallery.locator(".made-in-russia");
      await expect(stock).toHaveText("В наличии");
      await expect(origin).toHaveText("ПРОИЗВЕДЕНО В РОССИИ");
      await expect(gallery.locator(".product-gallery__badges")).toBeVisible();
      const stockBox = (await stock.boundingBox())!;
      const originBox = (await origin.boundingBox())!;
      const galleryBox = (await gallery.boundingBox())!;
      expect(stockBox.x + stockBox.width <= originBox.x || originBox.x + originBox.width <= stockBox.x || stockBox.y + stockBox.height <= originBox.y || originBox.y + originBox.height <= stockBox.y).toBe(true);
      for (const box of [stockBox, originBox]) {
        expect(box.x).toBeGreaterThanOrEqual(galleryBox.x);
        expect(box.y).toBeGreaterThanOrEqual(galleryBox.y);
        expect(box.x + box.width).toBeLessThanOrEqual(galleryBox.x + galleryBox.width);
        expect(box.y + box.height).toBeLessThanOrEqual(galleryBox.y + galleryBox.height);
      }
      await expect(page.getByText("Проверено", { exact: true }).first()).toBeVisible();
      await expect(page.getByText(/Проверено человеком/)).toHaveCount(0);
      await noOverflow(page);
    });
  }
}

test("the catalogue keeps supplier photos first and reveals the remaining products", async ({ page }) => {
  const assortment = Array.from({ length: 60 }, (_, index) => ({ ...products[index % products.length], id: `item-${index}`, images: index === 0 ? [{ id: "generated-photo", file_name: "Иллюстрация товара: Коробка.webp", content_type: "image/webp", position: 0 }, { id: "supplier-photo", file_name: "Фото товара.png", content_type: "image/png", position: 1 }] : index === 1 ? [{ id: "generated-only-photo", file_name: "Иллюстрация товара: Материал.webp", content_type: "image/webp", position: 0 }] : [] }));
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/products") ? assortment : [] }));
  await page.goto("/");
  await expect(page.locator(".market-product")).toHaveCount(10);
  await expect(page.locator(".market-product").first().locator("img")).toHaveAttribute("src", /product-images\/supplier-photo$/);
  await expect(page.locator(".market-product").nth(1).locator("img")).toHaveAttribute("src", /product-images\/generated-only-photo$/);
  await expect(page.locator(".market-product").nth(1).locator("img")).toHaveAttribute("alt", products[1].name);
  await expect(page.locator(".market-product .product-image-note")).toHaveCount(0);
  await expect(page.locator(".market-product").first().locator(".product-no-photo")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Популярные товары", exact:true })).toBeVisible();
  const titleBox = (await page.getByRole("heading", {name:"Популярные товары",exact:true}).boundingBox())!;
  const moreBox = (await page.getByRole("link", {name:/Показать ещё/}).boundingBox())!;
  expect(moreBox.x - titleBox.x - titleBox.width).toBeGreaterThanOrEqual(10);
  expect(moreBox.x - titleBox.x - titleBox.width).toBeLessThanOrEqual(24);

  await expect(page.locator(".catalog-filters")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Порядок товаров" })).toHaveCount(0);
  await page.getByRole("link", { name: /Показать ещё/ }).click();
  await expect(page).toHaveURL(/\/catalog$/);
  await page.goto("/catalog");
  await expect(page.locator(".market-product")).toHaveCount(30);
  await page.getByRole("button", { name: /Показать ещё/ }).click();
  await expect(page.locator(".market-product")).toHaveCount(60);
  await openCatalogFilters(page);
  await page.getByLabel("Цена от, ₽", { exact: true }).fill("1");
  await page.getByRole("button", { name: "Применить фильтры", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(30);
  await page.getByRole("button", { name: /Показать ещё/ }).click();
  await expect(page.locator(".market-product")).toHaveCount(60);
  await openCatalogFilters(page);
  await page.getByRole("button", { name: "Очистить фильтры", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(30);
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
    await compactProductBody(page, width < 760 ? 155 : 150);
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
    await expect(page.getByLabel("Электронная почта", { exact: false })).toBeVisible();
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

test("account drawer transitions can reverse without an old exit timer hiding the reopened panel", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-drawer-motion"));
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/auth/me") ? { user: { id: "drawer-user", first_name: "Анна", last_name: "Соколова", email: "buyer@example.test", is_marketplace_admin: false }, companies: [] } : [] }));
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/catalog");
  const trigger = page.getByRole("button", { name: "Открыть личный кабинет", exact: true });
  await trigger.click();
  const drawer = page.locator(".account-drawer");
  await expect(drawer).toHaveAttribute("data-state", "open");
  await expect(drawer).toHaveAttribute("data-motion", "animated");
  expect(await drawer.evaluate(element => getComputedStyle(element).transitionProperty)).toBe("transform, opacity");
  expect(await drawer.evaluate(element => getComputedStyle(element).transitionDuration)).toContain("0.22s");
  expect(await drawer.evaluate(element => getComputedStyle(element).animationName)).toBe("none");
  const sameDrawer = (await drawer.elementHandle())!;
  // Dispatch pointer clicks without waiting for the moving close target to settle.
  await drawer.getByRole("button", { name: "Закрыть", exact: true }).dispatchEvent("click", { detail: 1 });
  await expect(drawer).toHaveAttribute("data-state", "closed");
  await expect(drawer).toHaveAttribute("aria-hidden", "true");
  expect(await drawer.evaluate(element => (element as HTMLElement).inert)).toBe(true);
  await expect(page.getByRole("dialog", { name: "Меню аккаунта" })).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  await trigger.dispatchEvent("click", { detail: 1 });
  await expect(drawer).toHaveAttribute("data-state", "open");
  expect(await drawer.evaluate((element, previous) => element === previous, sameDrawer)).toBe(true);
  expect(await drawer.evaluate(element => (element as HTMLElement).inert)).toBe(false);
  await expect(drawer.getByRole("button", { name: "Закрыть", exact: true })).toBeFocused();
  // Pass the old exit deadline even if the reversing transition settles sooner.
  await page.waitForTimeout(260);
  await expect.poll(() => drawer.evaluate(element => getComputedStyle(element).transform)).toBe("matrix(1, 0, 0, 1, 0, 0)");
  await expect(page.getByRole("dialog", { name: "Меню аккаунта" })).toBeVisible();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
  await drawer.getByRole("link", { name: "Настройки", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(drawer).toHaveCount(0);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
});

test("account drawer uses instant reduced-motion and keyboard state changes with restored focus", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-drawer-keyboard"));
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/auth/me") ? { user: { id: "drawer-user", first_name: "Анна", last_name: "Соколова", email: "buyer@example.test", is_marketplace_admin: false }, companies: [] } : [] }));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/catalog");
  const trigger = page.getByRole("button", { name: "Открыть личный кабинет", exact: true });
  const drawer = page.locator(".account-drawer");
  await trigger.click();
  await expect(drawer).toHaveAttribute("data-motion", "instant");
  expect(await drawer.evaluate(element => getComputedStyle(element).transitionDuration)).toBe("0s");
  await drawer.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(drawer).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await trigger.press("Enter");
  await expect(drawer).toHaveAttribute("data-motion", "instant");
  expect(await drawer.evaluate(element => getComputedStyle(element).transitionDuration)).toBe("0s");
  await expect(drawer.getByRole("button", { name: "Закрыть", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
});

for (const direction of ["Tab", "Shift+Tab"]) {
  test(`account sheet keeps ${direction} inside while logout is pending`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("token", "synthetic-design-user"));
    let release: () => void = () => {};
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/auth/logout")) {
        await pending;
        return route.fulfill({ status: 503, json: { detail: "Временно недоступно" } });
      }
      return route.fulfill({ json: path.endsWith("/auth/me") ? { user: { id: "user-design", first_name: "Анна", last_name: "Соколова", email: "buyer@example.test", is_marketplace_admin: false }, companies: [] } : [] });
    });
    page.on("dialog", dialog => dialog.accept());
    await page.goto("/catalog");
    await page.getByRole("button", { name: "Открыть личный кабинет", exact: true }).click();
    const sheet = page.getByRole("dialog", { name: "Меню аккаунта" });
    await sheet.getByRole("button", { name: "Выйти", exact: true }).click();
    await expect(sheet.getByRole("button", { name: "Выходим…", exact: true })).toBeDisabled();
    await page.keyboard.press(direction);
    const expected = sheet.getByRole("button", { name: direction === "Tab" ? "Закрыть" : "Тема: светлая", exact: true });
    await expect(expected).toBeFocused();
    release();
    await expect(sheet.getByRole("alert")).toContainText("Повторите выход");
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Открыть личный кабинет", exact: true })).toBeFocused();
  });
}

test("home and catalogue retain truthful ordering and keyboard selection", async ({ page }) => {
  await publicApi(page);
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Порядок товаров" })).toHaveCount(0);
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
  await page.goto("/catalog");
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
