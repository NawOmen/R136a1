import { expect, test } from "@playwright/test";
import { russianMessage, validationMessage } from "../../apps/web/app/lib/russianMessages";
import { displayValue, russianLabel } from "../../apps/web/app/lib/presentation";
import { canonicalCharacteristicKey } from "../../apps/web/app/lib/categoryProfiles";
import { parseSizeRanges } from "../../apps/web/app/lib/capabilities";

test("errors, statuses and structured values have Russian presentation without changing keys", () => {
  expect(russianMessage("Failed to fetch")).toContain("Не удалось связаться");
  expect(russianMessage("Internal Server Error")).toContain("Не удалось выполнить");
  expect(validationMessage({ type: "missing", loc: ["body", "unmapped_field"], msg: "Field required" }, {})).toBe("«Значение»: заполните обязательное поле");
  expect(validationMessage({ type: "int_parsing", msg: "Input should be a valid integer", loc: ["body", "quantity_units"] }, { quantity_units: "Количество" })).toBe("«Количество»: введите корректное число");
  expect(displayValue({ status: "in_production", estimate_complete: false })).toBe("Статус: Производство; Полнота сметы: Нет");
  expect(russianLabel("not_a_real_status", "Статус уточняется")).toBe("Статус уточняется");
  expect(canonicalCharacteristicKey("Материал")).toBe("material");
  expect(parseSizeRanges("Диаметр, мм: 10: 120")).toEqual({ diameter_mm: [10, 120] });
  expect(displayValue("Qwen")).toBe("Qwen");
});

const company = { id: "00000000-0000-4000-8000-000000000010", display_name: "Синтетическая компания", country: "RU", verification_status: "draft", membership: { can_buy: true, can_sell: true, is_admin: true } };
const user = { id: "00000000-0000-4000-8000-000000000001", first_name: "Проверка", last_name: "Интерфейса", account_status: "active" };

test("first login opens a scoped next action instead of declaring a draft company ready", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-guidance"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user, companies: [company] } });
    if (path.endsWith("/next-step")) {
      expect(new URL(route.request().url()).searchParams.get("company_id")).toBe(company.id);
      return route.fulfill({ json: { title: "Завершите проверку компании", description: "Публикация доступна после проверки.", href: `/company/${company.id}` } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Завершите проверку компании" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Продолжить", exact: true })).toHaveAttribute("href", `/company/${company.id}`);
  await expect(page.getByText(/готова к работе/)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Выберите рабочий путь" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Закупки и статистика", exact: false })).toBeHidden();
  await page.getByText("Все рабочие разделы", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Закупки и статистика", exact: false })).toBeVisible();
});

test("native required field validation is Russian even with an English browser", async ({ page }) => {
  await page.goto("/register");
  await page.getByRole("button", { name: /Зарегистрироваться|Создать аккаунт/ }).click();
  const message = await page.locator('input[required]').first().evaluate(input => (input as HTMLInputElement).validationMessage);
  expect(message).toBe("Заполните обязательное поле.");
});

for (const mode of ["buy", "sell"] as const) {
  test(`market needs navigation follows selected work mode: ${mode}`, async ({ page }) => {
    await page.addInitScript(({ userId, companyId, mode }) => {
      localStorage.setItem("token", "synthetic-navigation");
      localStorage.setItem(`porukam:work-mode:${userId}:${companyId}`, mode);
    }, { userId: user.id, companyId: company.id, mode });
    await page.route("**/api/**", route => {
      if (new URL(route.request().url()).pathname.endsWith("/auth/me")) return route.fulfill({ json: { user, companies: [company] } });
      return route.fulfill({ json: [] });
    });
    await page.goto("/catalog");
    await expect(page.getByRole("navigation", { name: "Раздел рынка" }).getByRole("link", { name: "Потребности" }))
      .toHaveAttribute("href", mode === "buy" ? "/needs" : "/seller/requests");
  });
}

test("homepage distinguishes unavailable offers from an empty catalogue and retries", async ({ page }) => {
  let failed = true;
  await page.route("**/api/**", route => route.fulfill(failed
    ? { status: 503, json: { detail: "Предложения временно недоступны" } }
    : { json: [] }));
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось загрузить предложения" })).toBeVisible();
  await expect(page.getByText("Предложений пока нет", { exact: true })).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Повторить загрузку", exact: true }).click();
  await expect(page.getByText("Предложений пока нет", { exact: true })).toBeVisible();
});

test("optional product checks fail independently without hiding product or implying admission", async ({ page }) => {
  const product = { id: "00000000-0000-4000-8000-000000000090", name: "Синтетический товар", category: "Упаковка и тара", subcategory: "Бумажные стаканы", characteristics: {}, images: [], price_rub: "10.5", price_tiers: [], moq_units: 100, lead_time_days: 3, producer: { display_name: "Проверочный производитель", company_id: company.id, rating: null, reviews_count: 0 } };
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill(path.endsWith("/detail") ? { json: product } : { status: 503, json: { detail: "Временно недоступно" } });
  });
  await page.goto(`/catalog/${product.id}`);
  await expect(page.getByRole("heading", { name: product.name, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Запросить условия", exact: true })).toBeVisible();
  await expect(page.getByText("История цен временно недоступна.", { exact: false })).toBeVisible();
  await expect(page.getByText("Не удалось загрузить сведения о допуске.", { exact: false })).toBeVisible();
  await expect(page.getByText("Для этой категории правила проверки документов ещё не настроены.", { exact: false })).toHaveCount(0);
});

test("guest mobile access includes login, usable theme and reachable form before marketing copy", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await expect(page.locator("header").getByRole("link", { name: "Войти", exact: true })).toBeVisible();
  const email = page.getByLabel("Электронная почта", { exact: false });
  await expect(email).toBeInViewport();
  await page.getByRole("button", { name: "Включить светлую тему" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Включить тёмную тему" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("seller opens anonymized need without owner fields or buyer actions", async ({ page }) => {
  const feed = { id: "00000000-0000-4000-8000-000000000080", revision: 1, category: "Строительство", subcategory: "Крепёж", characteristics: { unit: "шт", thread: "М8" }, volume_units: 200, deadline_date: "2026-11-20", visibility: "open_anonymized", status: "open_for_offers", valid_until: null };
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-seller"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { user, companies: [{ ...company, membership: { can_sell: true, can_buy: false, is_admin: true } }] } });
    if (path.endsWith(`/needs/${feed.id}`)) return route.fulfill({ json: feed });
    return route.fulfill({ json: [] });
  });
  await page.goto(`/needs/${feed.id}`);
  await expect(page.getByRole("heading", { name: feed.category, exact: true })).toBeVisible();
  await expect(page.getByText("Вложения доступны только компании-покупателю.", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ваши предложения (0)" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Скачать", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Выбрать предложение", exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("need outage is retryable and is not reported as a missing need", async ({ page }) => {
  let failed = true;
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-buyer"));
  await page.route("**/api/**", route => {
    if (new URL(route.request().url()).pathname.endsWith("/auth/me")) return route.fulfill({ json: { user, companies: [company] } });
    return route.fulfill({ status: failed ? 503 : 404, json: { detail: failed ? "Сервис временно недоступен" : "Потребность не найдена" } });
  });
  await page.goto("/needs/00000000-0000-4000-8000-000000000080");
  await expect(page.getByRole("heading", { name: "Не удалось загрузить потребность", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Потребность не найдена", exact: true })).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Повторить загрузку", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Потребность не найдена", exact: true })).toBeVisible();
});


test("registration requires separate acknowledgements and sends the current registration contract", async ({page}) => {
  let registered: Record<string, unknown> | null = null;
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/register")) {registered=route.request().postDataJSON(); return route.fulfill({json:{user,access_token:"synthetic-new-account"}});}
    if (path.endsWith("/auth/me")) return route.fulfill({json:{user,companies:[]}});
    return route.fulfill({json:[]});
  });
  await page.goto("/register");
  await page.getByLabel("Фамилия", {exact:false}).fill("Проверка");
  await page.locator("#first_name").fill("Аккаунта");
  await page.getByLabel("Электронная почта", {exact:false}).fill("access@demo.ru");
  await page.getByLabel("Пароль", {exact:false}).fill("synthetic-access-password");
  const submit = page.getByRole("button", {name:"Зарегистрироваться", exact:true});
  await submit.click(); expect(registered).toBeNull();
  await page.getByRole("checkbox", {name:/Принимаю правила работы/}).check();
  await page.getByRole("checkbox", {name:/Ознакомлен с условиями обработки данных/}).check();
  await submit.click(); await expect(page).toHaveURL(/\/dashboard/);
  expect(registered).toMatchObject({rules_version:"rules-1",privacy_version:"privacy-1",rules_accepted:true,privacy_acknowledged:true});
});


test("editor can reject a document with malformed unconfirmed characteristics", async ({page}) => {
  let decision: Record<string, unknown> | null = null;
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-editor"));
  const document = {id:"00000000-0000-4000-8000-000000000091",name:"Заключение по товару",document_type:"specification_review",verification_status:"unverified"};
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({json:{user:{...user,is_category_editor:true},companies:[]}});
    if (path.endsWith("/editor/categories")) return route.fulfill({json:{registry:{groups:[],characteristic_fields:{}},registry_hash:"0".repeat(64)}});
    if (path.endsWith("/editor/documents")) return route.fulfill({json:decision ? []:[document]});
    if (path.endsWith(`/documents/${document.id}/decision`)) {decision=route.request().postDataJSON(); return route.fulfill({json:{...document,verification_status:"rejected"}});}
    return route.fulfill({json:[]});
  });
  await page.goto("/editor");
  await page.getByLabel("Подтверждённые характеристики", {exact:true}).fill("Не удалось подтвердить значения");
  await page.getByLabel("Заключение", {exact:true}).fill("Недостаточно сведений для подтверждения применимости");
  await page.getByRole("button", {name:"Отклонить с причиной", exact:true}).click();
  await expect(page.getByText("Решение по документу сохранено.", {exact:true})).toBeVisible();
  expect(decision).toMatchObject({decision:"rejected",confirms:null});
});


test("admin preserves a support answer on failed submission and shows the failure", async ({page}) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-admin"));
  const ticket={id:"00000000-0000-4000-8000-000000000092",subject:"Вопрос по получению",message:"Уточните порядок получения заказа",status:"new"};
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({json:{user:{...user,is_marketplace_admin:true},companies:[]}});
    if (path.endsWith("/admin/companies")) return route.fulfill({json:{companies:[]}});
    if (path.endsWith("/admin/users")) return route.fulfill({json:{users:[]}});
    if (path.endsWith(`/admin/support/tickets/${ticket.id}`)) return route.fulfill({status:503,json:{detail:"Не удалось сохранить ответ"}});
    if (path.endsWith("/admin/support/tickets")) return route.fulfill({json:[ticket]});
    return route.fulfill({json:[]});
  });
  await page.goto("/admin");
  await page.getByLabel("Ответ", {exact:true}).fill("Проверьте согласованную дату в карточке заказа.");
  await page.getByRole("button", {name:"Отправить ответ и закрыть", exact:true}).click();
  await expect(page.getByText("Не удалось сохранить ответ", {exact:true})).toBeVisible();
  await expect(page.getByLabel("Ответ", {exact:true})).toHaveValue("Проверьте согласованную дату в карточке заказа.");
  await page.getByRole("combobox", {name:"Статус",exact:true}).selectOption("verified");
  await page.getByRole("button", {name:"Применить фильтр",exact:true}).click();
  await expect(page.getByText("Нет компаний по выбранному фильтру.",{exact:true})).toBeVisible();
});


test("recovery does not claim email delivery on failure and allows retry", async ({page}) => {
  let failed = true;
  await page.route("**/api/**", route => route.fulfill(failed ? {status:503,json:{detail:"Восстановление по почте сейчас недоступно"}} : {status:202,json:{message:"Если аккаунт существует, письмо с кодом придёт на указанную почту."}}));
  await page.goto("/recover");
  await page.getByLabel("Почта аккаунта",{exact:true}).fill("access@demo.ru");
  await page.getByRole("button",{name:"Получить код на почту",exact:true}).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("сейчас недоступно");
  await expect(page.getByLabel("Почта аккаунта",{exact:true})).toHaveValue("access@demo.ru");
  failed = false;
  await page.getByRole("button",{name:"Получить код на почту",exact:true}).click();
  await expect(page.getByLabel("Код из письма",{exact:true})).toBeVisible();
});
