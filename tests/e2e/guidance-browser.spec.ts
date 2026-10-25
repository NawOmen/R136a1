import { expect, test } from "@playwright/test";

for (const width of [320, 390, 1280]) {
test(`guidance pages retain keyboard disclosures, actions and layout at ${width}px`, async ({ page }) => {
  await page.route("**/api/**", route => route.fulfill({ json: [] }));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/knowledge");
    await expect(page.getByRole("heading", { name: "Помощь с закупкой", exact: true })).toBeVisible();
    const faq = page.locator(".help-questions summary").first();
    await faq.focus(); await page.keyboard.press("Enter");
    await expect(page.getByText(/Участник компании включает оба права/)).toBeVisible();
    await page.getByLabel("Ваш вопрос", { exact: true }).fill("Как согласовать условия?");
    await page.getByRole("button", { name: "Спросить", exact: true }).click();
    await expect(page.locator(".help-assistant").getByRole("alert")).toContainText("Войдите");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.goto("/ai-procurement");
    await expect(page.getByRole("heading", { name: "Закупки с ИИ", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Создать потребность", exact: true }).first()).toHaveAttribute("href", "/needs/new");
    await expect(page.getByText("ИИ не меняет цену, мощность и резерв. Выгода не гарантирована — её проверяет расчёт.")).toBeVisible();
    await expect(page.locator(".guidance-flow li")).toHaveCount(3);
    await expect(page.locator(".guidance-disclosure")).toHaveCount(6);
    const role = page.locator(".guidance-disclosure summary").first();
    await role.focus(); await page.keyboard.press("Enter");
    await expect(page.getByText("Не выдумывает данные и не подтверждает спецификацию. Карточку проверяет покупатель.")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
}

test("the redesigned assistant preserves retry, input, loading protection and safe links", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("token", "synthetic-guidance-user"));
  let attempts = 0;
  let release: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/platform-assistant")) {
      attempts++;
      expect(route.request().postDataJSON()).toEqual({ question: "Как согласовать условия?" });
      if (attempts === 1) return route.fulfill({ status: 503, json: { detail: "Помощник временно недоступен" } });
      await gate;
      return route.fulfill({ json: { answer: "Проверьте условия и подтвердите их в сделке.", links: ["/deals", "https://untrusted.example.test", "/support"] } });
    }
    return route.fulfill({ json: path.endsWith("/auth/me") ? { user: { id: "guidance-user", first_name: "Анна", last_name: "Соколова", is_marketplace_admin: false }, companies: [] } : [] });
  });
  await page.goto("/knowledge");
  const question = page.getByLabel("Ваш вопрос", { exact: true });
  await question.fill("Как согласовать условия?");
  await page.getByRole("button", { name: "Спросить", exact: true }).click();
  await expect(page.locator(".help-assistant").getByRole("alert")).toContainText("Помощник временно недоступен");
  await expect(question).toHaveValue("Как согласовать условия?");
  for (const theme of ["light", "dark"]) {
    if (theme === "dark") await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
    const contrast = await page.getByRole("button", { name: "Понятно", exact: true }).evaluate(button => {
      const style = getComputedStyle(button);
      const luminance = (color: string) => {
        const channels = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => {
          const channel = value / 255;
          return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
        });
        return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
      };
      const foreground = luminance(style.color), background = luminance(style.backgroundColor);
      return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
    });
    expect(contrast).toBeGreaterThanOrEqual(4.5);
  }
  await page.getByRole("button", { name: "Включить светлую тему", exact: true }).click();
  await page.getByRole("button", { name: "Понятно", exact: true }).click();
  await page.getByRole("button", { name: "Спросить", exact: true }).click();
  await expect(page.getByRole("button", { name: "Думаю…", exact: true })).toBeDisabled();
  await expect(question).toBeDisabled();
  await page.locator(".help-assistant form").evaluate(form => (form as HTMLFormElement).requestSubmit());
  expect(attempts).toBe(2);
  release();
  await expect(page.locator(".assistant-answer")).toContainText("Проверьте условия");
  await expect(question).toBeEnabled();
  await expect(page.locator(".assistant-answer a")).toHaveCount(2);
  await expect(page.locator('.assistant-answer a[href="/deals"]')).toBeVisible();
  await expect(page.locator('.assistant-answer a[href^="https:"]')).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    for (const button of [page.getByRole("button", {name:"Спросить", exact:true}), page.locator('.assistant-answer a[href="/deals"]')]) {
      for (const hovered of [false, true]) {
        if (hovered) await button.hover(); else await page.mouse.move(0,0);
        await page.waitForTimeout(250);
        const ratio = await button.evaluate(el => {
          const css=getComputedStyle(el);
          const lum=(color:string)=>{const c=color.match(/[\d.]+/g)!.slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return c[0]*.2126+c[1]*.7152+c[2]*.0722;};
          const a=lum(css.color),b=lum(css.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        });
        expect(ratio).toBeGreaterThanOrEqual(4.5);
      }
    }
  }

});
