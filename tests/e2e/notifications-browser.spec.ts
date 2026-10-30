import { expect, test, type Page } from "@playwright/test";
const buyer = "40000000-0000-4000-8000-000000000001", seller = "40000000-0000-4000-8000-000000000002", otherSeller = "40000000-0000-4000-8000-000000000003";
const needId = "40000000-0000-4000-8000-000000000004", requestId = "40000000-0000-4000-8000-000000000005", dealId = "40000000-0000-4000-8000-000000000006";
const need = { id: needId, company_id: buyer, category: "Строительство", subcategory: "Крепёж", revision: 1, characteristics: { unit: "шт" }, volume_units: 20000, budget_rub: "100000", deadline_date: "2026-11-29", valid_until: "2026-11-29", status: "waiting_for_match", visibility: "open_anonymized", files: [], delivery_address_id: null, requirements_evidence: null };
const request = { id: requestId, need_id: needId, need_revision: 1, buyer_company_id: buyer, seller_company_id: otherSeller, buyer_name: "Синтетический покупатель Б", seller_name: "Синтетический поставщик Б", specification: { category: "Крепёж для Москвы", quantity: 20000, unit: "шт", deadline_date: need.deadline_date, characteristics: { unit: "шт" } }, status: "sent", revision: 1, quoted_price_rub: null, price_basis: "unknown", lead_time_days: null, delivery_date: null, note: "", sent_at: null, updated_at: null };
const firstRequest = { ...request, id: "40000000-0000-4000-8000-000000000007", buyer_name: "Синтетический покупатель А", seller_company_id: seller, seller_name: "Синтетический поставщик А" };

async function prepare(page: Page, options: { href?: string; type?: string; seller?: boolean; many?: boolean; readFailure?: boolean } = {}) {
  const companies = [buyer, seller, otherSeller].map((id, index) => ({ id, display_name: `Синтетическая компания ${index}`, full_name: "Синтетическая компания", country: "RU", legal_form: "ООО", verification_status: "verified", membership: { can_buy: id === buyer, can_sell: id !== buyer, is_admin: true } }));
  const count = options.many ? 25 : 1;
  const notices = Array.from({ length: count }, (_, index) => ({ id: `notice-${index}`, user_id: "synthetic-user", message: `Получено предложение № ${index + 1}`, type: options.type ?? "offer_received", href: options.href, is_read: false }));
  let reads = 0, dealLoads = 0;
  const writes: string[] = [];
  page.on("pageerror", error => { throw error; });
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-notification-ui"));
  await page.route("**/api/**", async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    if (req.method() !== "GET") writes.push(path);
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user: { id: "synthetic-user", first_name: "Тест", last_name: "Уведомления", account_status: "active" }, companies: options.seller ? companies.slice(1) : companies } });
    if (path.endsWith("/notifications")) return route.fulfill({ json: notices });
    if (/\/notifications\/[^/]+\/read$/.test(path)) {
      reads++;
      if (options.readFailure) return route.fulfill({ status: 503, json: { detail: "Не удалось сохранить прочтение" } });
      const item = notices.find(item => path.endsWith(`/${item.id}/read`))!;
      item.is_read = true;
      return route.fulfill({ json: item });
    }
    if (path.endsWith(`/needs/${needId}`)) return route.fulfill({ json: need });
    if (path.endsWith(`/needs/${needId}/offers`)) return route.fulfill({ json: [{ id: "offer", company_id: seller, status: "sent", price_rub: "4.80", available_units: 20000, lead_time_days: 2, moq_units: 1000, revision: 1, commercial_quote: null }] });
    if (path.endsWith("/needs/mine")) return route.fulfill({ json: [need] });
    if (path.endsWith("/deals/mine")) {
      dealLoads++;
      return route.fulfill({ json: ["40000000-0000-4000-8000-000000000008", dealId].map(id => ({ id, buyer_company_id: buyer, seller_company_id: seller, need_id: needId, units: 20000, total_price_rub: "96000", status: "created", commercial_snapshot: null })) });
    }
    if (path.includes("/deals/") && /\/(fulfillment|execution)$/.test(path)) return route.fulfill({ status: 503, json: { detail: "Исполнение временно недоступно" } });
    if (path.endsWith("/supplier-requests")) {
      const rows = options.seller && url.searchParams.get("company_id") === seller ? [firstRequest] : [firstRequest, request];
      return route.fulfill({ json: rows });
    }
    return route.fulfill({ json: [] });
  });
  return { notices, writes, reads: () => reads, dealLoads: () => dealLoads };
}

async function bell(page: Page) {
  await page.getByRole("button", { name: /Уведомления/ }).click();
  return page.getByRole("region", { name: "Уведомления", exact: true });
}

test("buyer opens the exact need directly from the bell even if read receipt fails", async ({ page }) => {
  const state = await prepare(page, { href: `/needs/${needId}`, readFailure: true });
  await page.goto("/notifications");
  const panel = await bell(page);
  await panel.getByRole("link", { name: state.notices[0].message, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/needs/${needId}$`));
  await expect(page.getByRole("heading", { name: "Строительство", exact: true })).toBeVisible();
  await expect(page.getByText(/КП offer/)).toBeVisible();
  await expect.poll(state.reads).toBe(1);
  expect(state.writes.every(path => path.endsWith("/read"))).toBe(true);
});

test("full notification list links to the specific deal and a new event refreshes an open deal page", async ({ page }) => {
  const state = await prepare(page, { href: `/deals?deal=${dealId}`, type: "offer_selected" });
  await page.goto("/notifications");
  await page.locator(".notification-message").click();
  await expect(page).toHaveURL(new RegExp(`deal=${dealId}`));
  await expect(page.locator(`[data-deal-id="${dealId}"]`)).toHaveAttribute("aria-pressed", "true");
  const loaded = state.dealLoads();
  const panel = await bell(page);
  await panel.getByRole("link", { name: state.notices[0].message, exact: true }).click();
  await expect.poll(state.dealLoads).toBeGreaterThan(loaded);
  await expect(page.locator(`[data-deal-id="${dealId}"]`)).toHaveAttribute("aria-pressed", "true");
});

test("legacy notifications still have a useful internal destination", async ({ page }) => {
  const state = await prepare(page);
  await page.goto("/notifications");
  await expect(page.locator(".notification-message")).toHaveAttribute("href", "/needs");
  await page.locator(".notification-message").click();
  await expect(page).toHaveURL(/\/needs$/);
  await expect.poll(state.reads).toBe(1);
});

test("seller notification selects the addressed company and the requested conversation", async ({ page }) => {
  await prepare(page, { seller: true, href: `/seller/inquiries?company=${otherSeller}&request=${requestId}`, type: "supplier_message_received" });
  await page.goto("/notifications");
  await page.locator(".notification-message").click();
  await expect(page.locator(".supplier-inbox__item[aria-pressed=true]")).toContainText(request.buyer_name);
  await expect(page.getByRole("region", { name: "Работа с поставщиком" })).toContainText(request.specification.category);
  await expect(page.getByLabel("Компания", { exact: true })).toHaveValue(otherSeller);
});

test("buyer notification opens the exact chat on the supplier board", async ({ page }) => {
  await prepare(page, { href: `/needs/${needId}/suppliers?request=${requestId}`, type: "supplier_message_received" });
  await page.goto("/notifications");
  await page.locator(".notification-message").click();
  await expect(page.getByRole("tab", { name: /Доска запросов/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "Работа с поставщиком" })).toContainText(request.specification.category);
});

test("failed action below the fold reveals and focuses its red error, including the same error again", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const state = await prepare(page, { many: true, readFailure: true });
  await page.goto("/notifications");
  const last = page.getByRole("button", { name: "Отметить прочитанным", exact: true }).last();
  const error = page.locator("main .alert-error");
  for (let attempt = 1; attempt <= 2; attempt++) {
    await last.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => scrollY)).toBeGreaterThan(500);
    if (attempt === 1) await last.click(); else await last.press("Enter");
    await expect(error).toContainText("Не удалось сохранить прочтение");
    await expect(error).toBeFocused();
    await expect.poll(() => error.evaluate(node => {
      const top = node.getBoundingClientRect().top;
      const header = document.querySelector(".site-header")!.getBoundingClientRect().bottom;
      return top >= header && top < innerHeight;
    })).toBe(true);
  }
  expect(state.reads()).toBe(2);
});
