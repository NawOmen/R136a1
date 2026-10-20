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
  await page.waitForLoadState("networkidle");
}

test("503, reload, role and company switching preserve independent input and source files", async ({ page }) => {
  await prepare(page);
  const description = page.locator("#request_description");
  await expect(page.getByText("Выбрать файлы", { exact: true })).toBeVisible();
  await expect(page.getByText("Файлы не выбраны", { exact: true })).toBeVisible();
  await expect(page.locator("#need_files")).toBeEnabled();
  await page.locator("#need_files").focus();
  await expect(page.locator("#need_files")).toBeFocused();
  await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Характеристика 1: название", exact: true })).toHaveValue("Единица заказа");
  await page.getByText("3. Карточка запроса — проверьте и отправьте", { exact: true }).click();
  await description.fill("Нужны столы из дерева, 30 штук, для офиса");
  // A readable label must not rename the persisted API characteristic key.
  await expect.poll(() => page.evaluate(() => Object.values(sessionStorage).some(value => {
    try { return JSON.parse(value).rows?.some((row: { key: string }) => row.key === "unit"); } catch { return false; }
  }))).toBe(true);
  await page.locator("#need_files").setInputFiles({ name: "синтетическая-спецификация.txt", mimeType: "text/plain", buffer: Buffer.from("Материал: дерево; количество: 30 шт") });
  await expect(page.getByText("Выбрано файлов: 1", { exact: true })).toBeVisible();
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
  await page.waitForLoadState("networkidle");
  await page.goto("/seller");
  await page.waitForLoadState("networkidle");
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
  await expect(page.getByText(/Не удалось получить доступ к микрофону|Запись с микрофона недоступна/)).toBeVisible();
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

test("clarified unreadable material is omitted by content hash while same-name valid file saves", async ({ page }) => {
  const { createHash } = await import("node:crypto");
  const { readFileSync } = await import("node:fs");
  const registry = JSON.parse(readFileSync(require.resolve("../../services/marketplace/app/category_registry.json"), "utf8"));
  await prepare(page);
  const bad = Buffer.from("synthetic corrupt content");
  const hash = createHash("sha256").update(bad).digest("hex");
  const properties = Object.entries({ product_type: "гофрокороб", dimensions_mm: "400×300×300", body_material: "картон", quantity_units: 250, budget_rub: 25000, lead_time_days: 14, delivery_city: "Москва" })
    .map(([key, value]) => ({ key, value, label: key, status: "assumed", confidence: 0.9, sources: [] }));
  let run = { id: "00000000-0000-4000-8000-000000000090", revision: 1, state: "needs_clarification", tool_calls: [],
    result: { category: "упаковка", properties, warnings: ["source.m4a: файл не прочитан"], matches: [], conflicts: [], summary: "Требуется уточнение", can_confirm: false,
      questions: [{ key: "unreadable_materials", question: "Часть материалов не прочитана. Продолжить без них?", options: ["Да, продолжить без них"] }],
      unreadable_sources: [{ source_id: "file_2", name: "source.m4a", content_hash: hash }], omitted_source_hashes: [] as string[] } };
  const needId = "00000000-0000-4000-8000-000000000091";
  const uploads: string[] = [];
  // WebKit's interception protocol omits File bytes from postDataBuffer even
  // for a new File(['text'], ...). Inspect the actual outgoing FormData in-page
  // as well as the request endpoint/count, without replacing or changing it.
  await page.addInitScript(() => {
    const original = window.fetch;
    Object.assign(window, { sourceUploads: [] as string[] });
    window.fetch = async (input, init) => {
      if (String(input).endsWith("/needs/00000000-0000-4000-8000-000000000091/files") && init?.body instanceof FormData) {
        const serialized = await new Response(init.body).text();
        (window as unknown as { sourceUploads: string[] }).sourceUploads.push(serialized);
      }
      return original(input, init);
    };
  });
  let creations = 0;
  await page.route("**/api/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user, companies: [{ ...companies[0], verification_status: "draft" }] } });
    if (path.endsWith("/categories/profiles")) return route.fulfill({ json: registry });
    if (path.endsWith("/addresses")) return route.fulfill({ json: [{ id: "00000000-0000-4000-8000-000000000092", city: "Москва", address: "ул. Синтетическая, д. 1", region: "Москва" }] });
    if (path.endsWith("/buyer-agent/runs") || path.endsWith(`/agent-runs/${run.id}`)) return route.fulfill({ status: 201, json: run });
    if (path.endsWith("/clarify")) {
      run = { ...run, revision: 2, state: "ready_for_review", result: { ...run.result, can_confirm: true, questions: [], omitted_source_hashes: [hash] } };
      return route.fulfill({ json: run });
    }
    if (path.endsWith("/confirm")) {
      run = { ...run, revision: 3, state: "confirmed_by_user" };
      return route.fulfill({ json: run });
    }
    if (path.endsWith("/physical-quantities/preview")) return route.fulfill({ json: { conversion: { factor: 1 } } });
    if (path.endsWith("/physical/needs") && request.method() === "POST") {
      creations++;
      expect(request.postDataJSON().subcategory).toBe("Коробки");
      expect(request.postDataJSON().deadline_date).toBe("2026-12-20");
      return route.fulfill({ status: 201, json: { id: needId, status: "draft" } });
    }
    if (path.endsWith(`/needs/${needId}/files`)) { uploads.push(request.postDataBuffer()!.toString()); return route.fulfill({ status: 201, json: { id: needId } }); }
    return route.fulfill({ json: [] });
  });
  await page.waitForLoadState("networkidle");
  await page.reload();
  await page.locator("#request_description").fill("Нужно 250 гофрокоробов 400×300×300 мм в Москву за 14 дней, бюджет 25000 рублей");
  await page.locator("#need_files").setInputFiles([
    { name: "source.m4a", mimeType: "text/plain", buffer: Buffer.from("valid synthetic source") },
    { name: "source.m4a", mimeType: "audio/mp4", buffer: bad },
  ]);
  await page.getByRole("button", { name: "Разобрать материалы", exact: true }).click();
  await page.getByLabel("Часть материалов не прочитана. Продолжить без них?").selectOption("Да, продолжить без них");
  await page.getByRole("button", { name: "Сохранить ответы", exact: true }).click();
  await expect(page.getByText(/По вашему решению непрочитанные материалы/)).toBeVisible();
  const volumeCheck = page.waitForResponse(response => response.url().endsWith("/physical-quantities/preview"));
  await page.getByRole("button", { name: "Перенести подтверждённые данные в карточку" }).click();
  await expect(page.locator("#subcategory")).toHaveValue("Коробки");
  await expect(page.locator("#delivery_address_id")).toHaveValue("00000000-0000-4000-8000-000000000092");
  await page.locator("#deadline_date").fill("20.12.26");
  await (await volumeCheck).finished();
  await expect(page.getByText("Проверяем точность объёма…", { exact: true })).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await page.reload();
  await expect(page.locator("#subcategory")).toHaveValue("Коробки");
  await expect(page.getByText(/По вашему решению непрочитанные материалы/)).toBeVisible();
  await page.getByRole("button", { name: "Сохранить черновик", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/needs/${needId}$`));
  expect(creations).toBe(1);
  expect(uploads).toHaveLength(1);
  expect(uploads[0]).toContain('filename="source.m4a"');
  const sourceUploads = await page.evaluate(() => (window as unknown as { sourceUploads: string[] }).sourceUploads);
  expect(sourceUploads).toHaveLength(1);
  expect(sourceUploads[0]).toContain("valid synthetic source");
  expect(sourceUploads[0]).not.toContain("synthetic corrupt content");
});

test("category guidance adds its required fields without cup-specific defaults", async ({ page }) => {
  const { readFileSync } = await import("node:fs");
  const registry = JSON.parse(readFileSync(require.resolve("../../services/marketplace/app/category_registry.json"), "utf8"));
  await prepare(page);
  await page.route("**/categories/profiles", route => route.fulfill({ json: registry }));
  await page.reload();
  await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
  await page.locator("#category").selectOption("Товары для бизнеса");
  await page.locator("#subcategory").selectOption("Мебель");
  await page.getByRole("button", { name: "Добавить недостающие обязательные поля" }).click();
  const keys = await page.locator('input[placeholder="Характеристика (например, материал)"]').evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value));
  expect(keys).toContain("Габариты, мм");
  expect(keys).not.toContain("Объём, мл");
  expect(new Set(keys).size).toBe(keys.length);
  await expect(page.getByRole("button", { name: "Добавить недостающие обязательные поля" })).toHaveCount(0);
});

test("narrow request form keeps file selection inside the viewport", async ({ page }) => {
  await prepare(page);
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/needs/new");
  const files = page.locator("#need_files");
  await expect(files).toBeVisible();
  await files.setInputFiles({ name: "Требования-к-закупке.txt", mimeType: "text/plain", buffer: Buffer.from("Синтетические требования") });
  await expect(page.getByText(/Восстановленные или выбранные файлы: 1/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
