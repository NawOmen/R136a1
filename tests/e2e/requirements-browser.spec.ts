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
  await expect(page.getByText("Фото, PDF, текст или аудио", { exact: true })).toBeVisible();
  await expect(page.locator("#need_files")).toBeEnabled();
  await page.locator("#need_files").focus();
  await expect(page.locator("#need_files")).toBeFocused();
  await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Характеристика 1: название", exact: true })).toHaveValue("Единица заказа");
  await page.getByRole("button", { name:"Изменить описание", exact:true }).click();
  await description.fill("Нужны столы из дерева, 30 штук, для офиса");
  // A readable label must not rename the persisted API characteristic key.
  await expect.poll(() => page.evaluate(() => Object.values(sessionStorage).some(value => {
    try { return JSON.parse(value).rows?.some((row: { key: string }) => row.key === "unit"); } catch { return false; }
  }))).toBe(true);
  await page.locator("#need_files").setInputFiles({ name: "синтетическая-спецификация.txt", mimeType: "text/plain", buffer: Buffer.from("Материал: дерево; количество: 30 шт") });
  await expect(page.getByText("Выбрано файлов: 1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Заполнить с ИИ", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Локальная модель недоступна" })).toBeVisible();
  await expect(description).toHaveValue(/30 штук/);
  await page.reload();
  await expect(description).toHaveValue(/30 штук/);
  await expect(page.getByText(/синтетическая-спецификация.txt/, {exact:true})).toBeVisible();
  // A different company gets a different draft, even in the same account.
  await page.locator("#company_id").selectOption(companies[1].id);
  await expect(description).toHaveValue("");
  await description.fill("Синтетическая заявка второй компании");
  await page.locator("#company_id").selectOption(companies[0].id);
  await expect(description).toHaveValue(/30 штук/);
  await expect(page.getByText(/синтетическая-спецификация.txt/, {exact:true})).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.goto("/seller");
  await page.waitForLoadState("networkidle");
  await page.goto("/needs/new");
  await expect(description).toHaveValue(/30 штук/);
  // A transport failure has the same preservation behavior as a 503.
  await page.route("**/api/v2/buyer-agent/runs", route => route.abort("internetdisconnected"));
  await page.getByRole("button", { name: "Заполнить с ИИ", exact: true }).click();
  await expect(page.getByRole("button", { name: "Заполнить с ИИ", exact: true })).toBeEnabled();
  await expect(description).toHaveValue(/30 штук/);
});

test("microphone denial keeps the local audio-file path available", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: () => Promise.reject(new DOMException("Denied", "NotAllowedError")) } }));
  await prepare(page);
  await page.getByRole("button", { name: /Продиктовать запрос/ }).click();
  await expect(page.getByText(/Не удалось получить доступ к микрофону|Запись с микрофона недоступна/)).toBeVisible();
  await page.locator("#need_files").setInputFiles({ name: "синтетическая-запись.wav", mimeType: "audio/wav", buffer: Buffer.from("synthetic-audio") });
  await expect(page.getByText(/синтетическая-запись.wav/, {exact:true})).toBeVisible();
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

test("need creation stays local and hides processing metadata", async ({ page }) => {
  await prepare(page);
  let submitted = "";
  await page.route("**/buyer-agent/runs", route => { submitted = route.request().postData() ?? ""; return route.fulfill({status:503,json:{detail:"Синтетический отказ"}}); });
  await page.locator("#request_description").fill("Нужно 5000 стаканов в Москву");
  await expect(page.locator("#analysis_route")).toHaveCount(0);
  await expect(page.getByText(/Пробные сценарии|Настройки обработки|Лимит и сохранение/)).toHaveCount(0);
  await page.getByRole("button",{name:"Заполнить с ИИ",exact:true}).click();
  await expect.poll(()=>submitted).toContain('name="route"');
  expect(submitted).toMatch(/name="route"\r?\n\r?\nlocal/);
  expect(submitted).toMatch(/name="external_context_allowed"\r?\n\r?\nfalse/);
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
  await page.getByRole("button", { name: "Заполнить с ИИ", exact: true }).click();
  await page.getByLabel("Часть материалов не прочитана. Продолжить без них?").selectOption("Да, продолжить без них");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(page.getByText(/По вашему решению непрочитанные материалы/)).toBeVisible();
  await expect(page.getByRole("heading", { name:"Детали закупки", exact:true })).toBeVisible();
  await expect(page.locator("#subcategory")).toHaveValue("Коробки");
  await expect(page.locator("#delivery_address_id")).toHaveValue("00000000-0000-4000-8000-000000000092");
  await page.locator("#deadline_date").fill("20.12.26");
  await expect(page.locator("#deadline_date")).toHaveValue("20.12.26");
  await expect.poll(() => page.evaluate(() => Object.entries(sessionStorage)
    .filter(([key]) => key.startsWith("porukam:need-draft:"))
    .map(([, value]) => JSON.parse(value).deadline))).toContain("2026-12-20");
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
  const keys = await page.locator('input[placeholder="Название характеристики"]').evaluateAll(inputs => inputs.map(input => (input as HTMLInputElement).value));
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
  await expect(files).toBeEnabled();
  await files.setInputFiles({ name: "Требования-к-закупке.txt", mimeType: "text/plain", buffer: Buffer.from("Синтетические требования") });
  await expect(page.getByText(/Требования-к-закупке.txt/, {exact:true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("address entry uses an accessible dialog, provider selection and retry without browser prompts", async ({ page }) => {
  await prepare(page);
  let saves = 0;
  const selected = { label: "г Новосибирск, ул Складская, д 12", address: "ул Складская, д 12", city: "Новосибирск", region: "Новосибирская область", house: "12" };
  page.on("dialog", () => { throw new Error("Native browser prompts must not be used for address entry"); });
  await page.route("**/address-suggestions?*", route => route.fulfill({ json: [selected] }));
  await page.route("**/addresses", route => {
    if (route.request().method() !== "POST") return route.fulfill({ json: [] });
    saves++;
    if (saves === 1) return route.fulfill({ status:503, json:{ detail:"Временная ошибка" } });
    expect(route.request().postDataJSON()).toMatchObject({ address:selected.address, city:selected.city, region:selected.region });
    return route.fulfill({ status:201, json:{ ...selected, id:"new-address", is_default:true } });
  });
  await page.setViewportSize({ width:390, height:844 });
  await page.getByRole("button", { name:"Заполнить вручную", exact:true }).click();
  await expect(page.locator("#visibility")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name:"Характеристика 1: значение", exact:true })).toHaveValue("шт");
  await page.getByRole("button", { name:"+ Добавить адрес", exact:true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByLabel("Поиск адреса", { exact:true }).fill("Новосибирск Складская 12");
  await page.getByRole("button", { name:selected.label, exact:true }).click();
  await expect(page.getByLabel("Регион", { exact:true })).toHaveValue(selected.region);
  await page.getByRole("button", { name:"Сохранить адрес", exact:true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("Не удалось сохранить");
  await expect(page.getByLabel("Улица, дом, строение", { exact:true })).toHaveValue(selected.address);
  await page.getByRole("button", { name:"Сохранить адрес", exact:true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("#delivery_address_id")).toHaveValue("new-address");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path:"../../output/playwright/need-mobile.png", fullPage:true });
});

test("support chat preserves failed text and notification bell opens full messages", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-chat"));
  const notification = { id:"notice", type:"support_ticket_updated", message:"Ответ поддержки: уточните номер склада для доставки.", is_read:false };
  let attempt = 0;
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json:{ user, companies } });
    if (path.endsWith("/notifications")) return route.fulfill({ json:[notification] });
    if (path.endsWith("/read")) return route.fulfill({ json:{ ...notification, is_read:true } });
    if (path.endsWith("/support/tickets") && route.request().method() === "POST") {
      expect(route.request().postDataJSON().subject).toBe("Поддержка: Доставка и получение");
      attempt++;
      if (attempt === 1) return route.fulfill({ status:503, json:{ detail:"Недоступно" } });
      return route.fulfill({ status:201, json:{ id:"message", message:route.request().postDataJSON().message, subject:route.request().postDataJSON().subject, status:"new", company_id:null, admin_response:null, created_at:"2026-10-23T12:00:00Z", updated_at:"2026-10-23T12:00:00Z" } });
    }
    return route.fulfill({ json:[] });
  });
  await page.setViewportSize({ width:390, height:844 });
  await page.goto("/support");
  await page.getByLabel("Тема вопроса", { exact:true }).selectOption("Доставка и получение");
  await page.getByLabel("Сообщение поддержке", { exact:true }).fill("Помогите уточнить адрес склада для заказа");
  await page.getByRole("button", { name:"Отправить", exact:true }).click();
  await expect(page.locator(".support-chat > [role=alert]")).toContainText("не отправлено");
  await expect(page.getByLabel("Сообщение поддержке", { exact:true })).toHaveValue(/адрес склада/);
  await page.getByRole("button", { name:"Отправить", exact:true }).click();
  await expect(page.getByRole("log")).toContainText("Помогите уточнить адрес склада");
  await expect(page.getByRole("log")).toContainText("Доставка и получение");
  await expect(page.getByLabel("Сообщение поддержке", { exact:true })).toHaveValue("");
  await page.getByRole("button", { name:/Уведомления, новых/ }).click();
  await page.getByRole("button", { name:notification.message, exact:true }).click();
  await expect(page.locator(".notification-detail")).toContainText(notification.message);
  await expect(page.locator(".notification-detail a")).toHaveAttribute("href", "/support");
  await page.keyboard.press("Escape");
  await expect(page.locator(".notification-popover")).toHaveCount(0);
  await expect(page.getByRole("button", { name:/Уведомления/ })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path:"../../output/playwright/support-mobile.png", fullPage:true });
});

test("AI fills a single review card with compact decimals and stale confirmation cannot publish", async ({ page }) => {
  await prepare(page);
  let confirmations = 0, creations = 0;
  const facts = { product_type:"гофрокороб", dimensions_mm:"400×300×300", body_material:"картон", quantity_units:"100.000000000000", budget_rub:"12500.500000000000", lead_time_days:14, delivery_city:"Москва" };
  const run = { id:"00000000-0000-4000-8000-000000000090", revision:1, state:"ready_for_review", tool_calls:[], result:{ category:"упаковка", summary:"Техническая сводка", can_confirm:true, questions:[],conflicts:[],warnings:[],matches:[],properties:Object.entries(facts).map(([key,value])=>({key,value,label:key,status:"assumed",confidence:.95,sources:[{source_id:"text",excerpt:"Описание покупателя"}]})) } };
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({json:{user,companies}});
    if (path.endsWith("/addresses")) return route.fulfill({json:[{id:"address",city:"Москва",address:"ул. Складская, д. 1",region:"Москва"}]});
    if (path.endsWith("/buyer-agent/runs")) return route.fulfill({json:run});
    if (path.endsWith("/confirm")) { confirmations++; return route.fulfill({status:409,json:{detail:"Требования изменились. Повторите анализ."}}); }
    if (path.endsWith("/physical/needs") && route.request().method()==="POST") creations++;
    if (path.endsWith("/physical-quantities/preview")) return route.fulfill({json:{conversion:{factor:1}}});
    return route.fulfill({json:[]});
  });
  await page.reload();
  await page.locator("#request_description").fill("Нужно 100 коробок, доставка в Москву");
  await page.getByRole("button",{name:"Заполнить с ИИ",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Детали закупки",exact:true})).toBeVisible();
  await expect(page.locator("#volume_units")).toHaveValue("100");
  await expect(page.locator("#budget_rub")).toHaveValue("12500.5");
  await expect(page.locator("#request_description")).toHaveCount(0);
  await expect(page.getByText(/Откуда взята характеристика|Уверенность извлечения|Техническая сводка|Журнал обработки/)).toHaveCount(0);
  expect(confirmations).toBe(0);
  await page.screenshot({path:"../../output/playwright/need-review.png",fullPage:true});
  await page.getByRole("button",{name:"Подтвердить и опубликовать",exact:true}).click();
  await expect(page.locator(".need-workflow [role=alert]")).toContainText("Требования изменились");
  expect(confirmations).toBe(1);
  expect(creations).toBe(0);
  await expect(page.locator("#budget_rub")).toHaveValue("12500.5");
});
