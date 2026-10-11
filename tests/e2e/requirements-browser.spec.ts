import { expect, test, Page } from "@playwright/test";
const user = { id: "00000000-0000-4000-8000-000000000001", first_name: "Тест", last_name: "Покупатель", account_status: "active" };
const companies = ["Первая", "Вторая"].map((name, index) => ({ id: `00000000-0000-4000-8000-00000000001${index}`, display_name: name, full_name: name, country: "RU", legal_form: "ООО", verification_status: "verified", membership: { can_buy: true, can_sell: true, is_admin: true } }));
async function prepare(page: Page) {
  page.on("pageerror", error => { throw error; });
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-browser-test"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user, companies } });
    if (path.endsWith("/categories/profiles")) return route.fulfill({ json: { groups: [], characteristic_fields: {} } });
    if (path.endsWith("/physical-quantities/preview")) return route.fulfill({ json: { conversion: { factor: 1 } } });
    if (path.endsWith("/buyer-agent/runs")) return route.fulfill({ status: 503, json: { detail: "Локальная модель недоступна" } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/needs/new");
  await expect(page.locator("#company_id")).toHaveValue(companies[0].id);
}

test("503, reload, role and company switching preserve independent input and source files", async ({ page }) => {
  await prepare(page);
  const description = page.locator("#request_description");
  await description.fill("Нужны столы из дерева, 30 штук, для офиса");
  await page.locator("#need_files").setInputFiles({ name: "синтетическая-спецификация.txt", mimeType: "text/plain", buffer: Buffer.from("Материал: дерево; количество: 30 шт") });
  await page.getByRole("button", { name: "Разобрать материалы", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Локальная модель недоступна" })).toBeVisible();
  await expect(description).toHaveValue(/30 штук/);
  await page.reload();
  await expect(description).toHaveValue(/30 штук/);
  await expect(page.getByText(/Восстановленные или выбранные файлы: 1/)).toBeVisible();
  // A different company gets a different draft, even in the same account.
  await page.locator("#company_id").selectOption(companies[1].id);
  await expect(description).toHaveValue("");
  await description.fill("Синтетическая заявка второй компании");
  await page.locator("#company_id").selectOption(companies[0].id);
  await expect(description).toHaveValue(/30 штук/);
  await expect(page.getByText(/Восстановленные или выбранные файлы: 1/)).toBeVisible();
  await page.goto("/seller");
  await page.goto("/needs/new");
  await expect(description).toHaveValue(/30 штук/);
  // A transport failure has the same preservation behavior as a 503.
  await page.route("**/api/v2/buyer-agent/runs", route => route.abort("internetdisconnected"));
  await page.getByRole("button", { name: "Разобрать материалы", exact: true }).click();
  await expect(page.getByRole("button", { name: "Разобрать материалы", exact: true })).toBeEnabled();
  await expect(description).toHaveValue(/30 штук/);
});

test("microphone denial keeps the local audio-file path available", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: () => Promise.reject(new DOMException("Denied", "NotAllowedError")) } }));
  await prepare(page);
  await page.getByRole("button", { name: /Продиктовать запрос/ }).click();
  await expect(page.getByText(/Не удалось получить доступ к микрофону/)).toBeVisible();
  await page.locator("#need_files").setInputFiles({ name: "синтетическая-запись.wav", mimeType: "audio/wav", buffer: Buffer.from("synthetic-audio") });
  await expect(page.getByText(/Восстановленные или выбранные файлы: 1/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/синтетическая-запись.wav/)).toBeVisible();
});

test("S13: expiry warnings follow document deletion and company scope; failures can be retried", async ({ page }) => {
  const document = { id: "00000000-0000-4000-8000-000000000050", company_id: companies[0].id,
    name: "Синтетическое подтверждение А", document_type: "certificate", verification_status: "verified",
    scope_category: "Упаковка и тара", scope_subcategory: "Бумажные стаканы", confirms: {},
    valid_until: "2026-10-20", created_at: "2026-10-11T00:00:00Z", content_type: "application/pdf" };
  let deleted = false;
  let expiryFailed = true;
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-browser-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user, companies } });
    if (route.request().method() === "DELETE") { deleted = true; return route.fulfill({ status: 204 }); }
    if (path.endsWith("/documents/expiring") && path.includes(companies[1].id)) {
      await new Promise(resolve => setTimeout(resolve, 300));
      return expiryFailed ? route.fulfill({ status: 503, json: { detail: "Сроки временно не проверяются" } }) : route.fulfill({ json: [] });
    }
    if (path.includes("/documents")) return route.fulfill({ json: path.includes(companies[0].id) && !deleted ? [document] : [] });
    return route.fulfill({ json: [] });
  });
  await page.goto("/seller/documents");
  await expect(page.getByRole("heading", { name: "Истекающие подтверждения" })).toBeVisible();
  page.on("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page.getByText(document.name, { exact: false })).toHaveCount(0);
  await page.locator("#seller_company").selectOption(companies[1].id);
  await expect(page.getByText(document.name, { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Повторить проверку сроков" })).toBeVisible();
  await expect(page.getByText("Истекающих подтверждений нет.")).toHaveCount(0);
  expiryFailed = false;
  await page.getByRole("button", { name: "Повторить проверку сроков" }).click();
  await expect(page.getByText("Истекающих подтверждений нет.")).toBeVisible();
});

test("S13: external counters need an explicit separate choice and a different retry key", async ({ page }) => {
  await prepare(page);
  const submitted: string[] = [];
  await page.route("**/buyer-agent/runs", route => {
    submitted.push(route.request().postData() ?? "");
    return route.fulfill({ status: 503, json: { detail: "Синтетический отказ" } });
  });
  await page.locator("#request_description").fill("Нужно 5000 стаканов в Москву");
  await page.locator("#analysis_route").selectOption("complex_auto");
  const consent = page.getByRole("checkbox", { name: /Разрешаю передать внешней модели DeepSeek/ });
  await expect(consent).not.toBeChecked();
  await page.getByRole("button", { name: "Разобрать материалы", exact: true }).click();
  await expect(page.getByRole("button", { name: "Разобрать материалы", exact: true })).toBeEnabled();
  await consent.check();
  await page.getByRole("button", { name: "Разобрать материалы", exact: true }).click();
  await expect.poll(() => submitted.length).toBe(2);
  expect(submitted[0]).toMatch(/name="external_context_allowed"\r?\n\r?\nfalse/);
  expect(submitted[1]).toMatch(/name="external_context_allowed"\r?\n\r?\ntrue/);
  const key = (body: string) => /name="request_key"\r?\n\r?\n([^\r\n]+)/.exec(body)?.[1];
  expect(key(submitted[0])).not.toBe(key(submitted[1]));
});
