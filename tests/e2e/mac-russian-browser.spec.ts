import { expect, test, type Page } from "@playwright/test";

async function prepare(page: Page, signedIn = false) {
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  if (signedIn) await page.addInitScript(() => localStorage.setItem("token", "synthetic-russian-ui"));
  const company = { id: "00000000-0000-4000-8000-000000000010", display_name: "Синтетический производитель", verification_status: "verified", country: "RU", membership: { can_buy: true, can_sell: true, is_admin: true } };
  const products = [100, 0, 100, null].map((stock, i) => ({ id: `stock-${i}`, name: `Коробки ${i + 1}`, company_id: company.id, category: "Упаковка и тара", characteristics: { unit: "pcs" }, price_rub: "38.123456789124", price_tiers: [{ min_units: 1000, unit_price_rub: "38.123456789123" }], moq_units: 100, lead_time_days: 7, images: [], stock_units: stock, stock_updated_at: i === 2 ? "2000-01-01T00:00:00Z" : new Date().toISOString() }));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith("/products") ? products : path.endsWith("/auth/me") ? { user: { id: "00000000-0000-4000-8000-000000000001", first_name: "Тест", last_name: "Интерфейса" }, companies: [company] } : path.endsWith("/categories/profiles") ? { groups: [], characteristic_fields: {} } : [] });
  });
  return errors;
}

test("stock labels and exact starting prices stay readable in both themes", async ({ page }, info) => {
  const errors = await prepare(page);
  await page.goto("/");
  const cards = page.locator(".market-product");
  await expect(cards).toHaveCount(4);
  await expect(cards.nth(0).locator(".product-stock")).toHaveText("В наличии");
  await expect(cards.nth(1).locator(".product-stock")).toHaveText("Нет в наличии");
  await expect(cards.nth(2).locator(".product-stock")).toHaveText("Уточнить наличие");
  await expect(cards.nth(3).locator(".product-stock")).toHaveText("Уточнить наличие");
  await expect(cards.first().locator(".market-price")).toHaveText("от 38,123456789123 ₽");
  await expect(cards.first().locator(".product-conditions")).toHaveText("От 100 шт.");
  await expect(cards.first().locator(".product-pricing")).toHaveAttribute("title", /при заказе от 1\s000 шт\./);
  await expect(cards.first().locator(".market-muted")).toHaveText("/ шт.");
  for (const theme of ["light", "dark"]) {
    await page.locator("html").evaluate((element, value) => element.dataset.theme = value, theme);
    await page.evaluate(() => { (document.activeElement as HTMLElement)?.blur(); scrollTo(0, 0); });
    await page.screenshot({ path: info.outputPath(`stock-${theme}.png`), animations: "disabled" });
    const badge = (await cards.first().locator(".product-stock").boundingBox())!, image = (await cards.first().locator(".market-product__visual").boundingBox())!;
    expect(badge.y).toBeGreaterThanOrEqual(image.y);
    expect(badge.y + badge.height).toBeLessThan(image.y + image.height);
    const contrasts = await cards.locator(".product-stock").evaluateAll(items => {
      const luminance = (color: string) => {
        const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => {
          const channel = value / 255;
          return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
        });
        return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
      };
      return items.map(item => {
        const style = getComputedStyle(item), foreground = luminance(style.color), background = luminance(style.backgroundColor);
        return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
      });
    });
    expect(Math.min(...contrasts)).toBeGreaterThanOrEqual(4.5);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("Russian date input and calendar validate dates while drafts retain ISO", async ({ page }, info) => {
  const errors = await prepare(page, true);
  await page.goto("/needs/new");
  await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
  const date = page.locator("#deadline_date");
  await date.fill("290226");
  await expect(date).toHaveValue("29.02.26");
  await expect.poll(() => date.evaluate((el: HTMLInputElement) => el.validationMessage)).toBe("Введите дату в формате дд.мм.гг.");
  await date.fill("290228");
  await expect(date).toHaveValue("29.02.28");
  await date.fill("");
  await date.pressSequentially("290228");
  await expect(date).toHaveValue("29.02.28");
  await expect.poll(() => date.evaluate((el: HTMLInputElement) => el.validity.valid)).toBe(true);
  const stored = () => page.evaluate(() => Object.entries(sessionStorage).filter(([key]) => key.startsWith("porukam:need-draft:")).map(([, value]) => JSON.parse(value).deadline));
  await expect.poll(stored).toContain("2028-02-29");
  await date.locator("..").getByRole("button", { name: "Открыть календарь", exact: true }).click();
  const calendar = page.getByRole("dialog", { name: "Выбрать дату", exact: true });
  await expect(calendar).toContainText("февраль");
  await expect(calendar.getByRole("button", { name: "29.02.28", exact: true })).toBeFocused();
  await calendar.getByRole("button", { name: "Следующий месяц", exact: true }).click();
  await calendar.getByRole("button", { name: "01.03.28", exact: true }).click();
  await expect(date).toHaveValue("01.03.28");
  await expect(calendar).toHaveCount(0);
  await expect.poll(stored).toContain("2028-03-01");
  await date.locator("..").getByRole("button", { name: "Открыть календарь", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(calendar).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await page.reload();
  await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
  await expect(date).toHaveValue("01.03.28");
  await date.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("russian-date.png"), animations: "disabled" });
  // A six-row month must also stay inside a short mobile viewport.
  await date.fill("01.08.27");
  await date.locator("..").getByRole("button", { name: "Открыть календарь", exact: true }).click();
  const bounds = (await calendar.boundingBox())!;
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await page.screenshot({ path: info.outputPath("russian-calendar.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("a corrupt GPU framebuffer never replaces the CSS material", async ({ page, isMobile }) => {
  test.skip(isMobile, "Touch already uses the static material.");
  const errors = await prepare(page);
  await page.addInitScript(() => {
    const read = WebGLRenderingContext.prototype.readPixels;
    WebGLRenderingContext.prototype.readPixels = function(...args: Parameters<typeof read>) {
      Reflect.apply(read, this, args);
      const bytes = args[6];
      if (bytes instanceof Uint8Array) for (let i = 3; i < bytes.length; i += 4) bytes[i] = 255;
    };
  });
  await page.goto("/ai-procurement");
  const hero = page.locator(".guidance-hero");
  await expect(hero).toHaveAttribute("data-glass-fallback", "invalid-frame", { timeout: 15000 });
  await expect(hero).not.toHaveAttribute("data-mesh-ready", "true");
  await expect(hero.locator(".liquid-surface__material")).toBeVisible();
  await expect(page.getByRole("link", { name: "Создать потребность", exact: true }).first()).toBeVisible();
  expect(errors).toEqual([]);
});

for (const failure of ["dark-preflight", "rgb-preflight", "theme-change", "pointer-entry", "settled-motion"] as const) {
  test(`glass rejects ${failure} corruption and retains readable moving material`, async ({ page, isMobile }, info) => {
    test.skip(isMobile, "Touch uses the static material.");
    const errors = await prepare(page);
    await page.addInitScript(mode => {
      const read = WebGLRenderingContext.prototype.readPixels;
      WebGLRenderingContext.prototype.readPixels = function(...args: Parameters<typeof read>) {
        Reflect.apply(read, this, args);
        const program = this.getParameter(this.CURRENT_PROGRAM) as WebGLProgram;
        const dark = program && this.getUniform(program, this.getUniformLocation(program, "u_dark"));
        const pointer = program && this.getUniform(program, this.getUniformLocation(program, "u_pointer")) as Float32Array | null;
        const armed = mode === "rgb-preflight" || (mode === "dark-preflight" ? dark === 1 : (window as Window & { corruptGlass?: boolean }).corruptGlass && (mode !== "settled-motion" || pointer && Math.abs(pointer[0]) > .2));
        const pixels = args[6];
        if (armed && pixels instanceof Uint8Array) for (let i = 0; i < pixels.length; i += 4) {
          if (mode === "rgb-preflight") pixels[i] = pixels[i + 1] = pixels[i + 2] = 255;
          else pixels[i + 3] = 255;
        }
      };
    }, failure);
    await page.goto("/");
    const shell = page.locator(".storefront-hero .liquid-action"), material = shell.locator(".liquid-surface__material"), canvas = shell.locator("canvas"), copy = shell.locator("a");
    if (!["dark-preflight", "rgb-preflight"].includes(failure)) {
      await expect(canvas).toHaveAttribute("data-ready", "true");
      await page.evaluate(() => { (window as Window & { corruptGlass?: boolean }).corruptGlass = true; });
      if (failure === "theme-change") await page.locator("html").evaluate(el => el.dataset.theme = "dark");
      else if (failure === "settled-motion") { const box = (await shell.boundingBox())!; await page.mouse.move(box.x + box.width * .85, box.y + box.height * .2); }
      else await shell.hover({ position: { x: 30, y: 15 } });
    }
    await expect(shell).toHaveAttribute("data-glass-fallback", "invalid-frame");
    await expect(canvas).not.toHaveAttribute("data-ready", "true");
    await expect(material).toBeVisible();
    await page.locator(".page-surface").evaluate(async el => { await document.fonts.ready; await Promise.all(el.getAnimations().map(animation => animation.finished)); });
    await page.mouse.move(1, 1);
    await expect.poll(() => shell.evaluate(el => el.style.getPropertyValue("--glass-tilt-x"))).toBe("");
    const bounds = await copy.boundingBox();
    const box = (await shell.boundingBox())!;
    await page.mouse.move(box.x + box.width * .85, box.y + box.height * .2);
    await expect.poll(() => shell.evaluate(el => el.style.getPropertyValue("--glass-tilt-x"))).not.toBe("");
    await expect.poll(() => material.evaluate(el => getComputedStyle(el).transform)).toContain("matrix3d");
    expect(await copy.boundingBox()).toEqual(bounds);
    for (const theme of ["light", "dark"]) {
      await page.locator("html").evaluate((el, value) => el.dataset.theme = value, theme);
      await page.screenshot({ path: info.outputPath(`${failure}-${theme}.png`), animations: "disabled" });
      expect(await canvas.evaluate(el => getComputedStyle(el).opacity)).toBe("0");
    }
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect.poll(() => material.evaluate(el => getComputedStyle(el).transform)).toBe("none");
    await copy.click();
    await expect(page).toHaveURL(/\/needs\/new|\/login/);
    expect(errors).toEqual([]);
  });
}

test("both guidance shells keep readable actions across the Mac screenshot themes", async ({ page, isMobile }, info) => {
  test.skip(isMobile, "Desktop comparison uses the Mac screenshot dimensions.");
  const errors = await prepare(page);
  await page.setViewportSize({ width: 1280, height: 714 });
  for (const path of ["/ai-procurement", "/knowledge"]) {
    await page.waitForLoadState("networkidle");
    await page.goto(path);
    const hero = page.locator(".guidance-hero");
    await expect(hero.getByRole("link", { name: "Создать потребность", exact: true })).toBeVisible();
    const webgl2 = await page.evaluate(() => {
      const gl = document.createElement("canvas").getContext("webgl2");
      const supported = Boolean(gl); gl?.getExtension("WEBGL_lose_context")?.loseContext(); return supported;
    });
    if (webgl2) await expect(hero.locator(".hero-object__canvas")).toHaveAttribute("data-ready", "true", { timeout: 30000 });
    for (const theme of ["light", "dark"]) {
      await page.locator("html").evaluate((el, value) => el.dataset.theme = value, theme);
      await hero.locator(".hero-object__poster").evaluate(async el => {
        const image = new Image(); image.src = getComputedStyle(el).backgroundImage.slice(5, -2); await image.decode();
      });
      await page.evaluate(() => { (document.activeElement as HTMLElement)?.blur(); scrollTo(0, 0); });
      await page.screenshot({ path: info.outputPath(`${path === "/knowledge" ? "help" : "ai"}-${theme}.png`), animations: "disabled" });
      const colors = await hero.locator("h1").evaluate(el => { const css = getComputedStyle(el); return { color: css.color, background: getComputedStyle(document.body).backgroundColor }; });
      expect(colors.color).not.toBe(colors.background);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }
  expect(errors).toEqual([]);
});
