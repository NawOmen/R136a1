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
