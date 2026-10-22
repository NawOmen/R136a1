import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const user = { id: "00000000-0000-4000-8000-000000000001", first_name: "Тест", last_name: "Совместимости", email: "compat@example.test", account_status: "active" };
const company = { id: "00000000-0000-4000-8000-000000000010", display_name: "Синтетическая компания", verification_status: "verified", country: "RU", membership: { can_buy: true, can_sell: true, is_admin: true } };
const products = ["Коробки для отправки", "Кабель для оборудования", "Рабочая одежда", "Питьевая вода"].map((name, i) => ({
  id: `item-${i}`, name, category: i === 1 ? "Электроника" : "Упаковка и тара", characteristics: { unit: "шт" },
  price_rub: "38.123456789123", moq_units: 100, lead_time_days: 3, images: [{ id: `photo-${i}`, file_name: "Иллюстрация товара: пример.webp", position: 0 }],
}));
async function prepare(page: Page, signedIn = false) {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  if (signedIn) await page.addInitScript(() => localStorage.setItem("token", "synthetic-compatibility"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    if (path.includes("product-images/")) return route.fulfill({ headers, contentType: "image/webp", body: readFileSync(resolve(__dirname, "../../services/marketplace/seed_media/box.webp")) });
    return route.fulfill({ headers, json: path.endsWith("/auth/me") ? { user, companies: [company] } : path.endsWith("/products") ? products : path.endsWith("/categories/profiles") ? { groups: [], characteristic_fields: {} } : path.endsWith("/physical-quantities/preview") ? { conversion: { factor: 1 } } : [] });
  });
  return errors;
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}
async function captureViewport(page: Page, path: string) {
  await page.evaluate(() => { (document.activeElement as HTMLElement)?.blur(); window.scrollTo(0, 0); });
  await expect.poll(() => page.locator(".site-header").evaluate(el => el.getBoundingClientRect().top)).toBe(0);
  // A viewport capture avoids WebKit's full-page sticky-layer repositioning.
  await page.screenshot({ path, animations: "disabled" });
}

test("catalogue images, exact prices, sorting, touch controls and both themes remain usable", async ({ page, isMobile }, testInfo) => {
  const errors = await prepare(page);
  await page.goto("/");
  await expect(page.locator(".market-product")).toHaveCount(4);
  await expect(page.locator(".market-price").first()).toContainText("38,123456789123");
  await expect.poll(() => page.locator(".market-product img").first().evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  const visual = (await page.locator(".market-product__visual").first().boundingBox())!;
  const image = (await page.locator(".market-product img").first().boundingBox())!;
  // A percentage-height image in a grid can retain its intrinsic square height
  // despite object-fit:contain, cropping its bottom in the shallow photo frame.
  expect(image.y).toBeGreaterThanOrEqual(visual.y);
  expect(image.y + image.height).toBeLessThanOrEqual(visual.y + visual.height + 1);
  expect(image.width).toBeLessThanOrEqual(visual.width + 1);
  expect(await page.locator(".market-product__visual").evaluateAll(items => items.every(item => getComputedStyle(item).backgroundImage === "none"))).toBe(true);
  const favorite = page.locator(".product-favorite").first();
  if (isMobile) await favorite.tap(); else await favorite.click();
  await expect(favorite).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Электроника", exact: true }).click();
  await expect(page.locator(".market-product")).toHaveCount(1);
  await page.getByRole("button", { name: "Все категории", exact: true }).click();
  await page.getByRole("combobox", { name: "Порядок товаров" }).selectOption("name");
  await expect(page.locator(".market-product h2").first()).toHaveText("Кабель для оборудования");
  for (const theme of ["light", "dark"]) {
    if (theme === "dark") await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const colors = await page.locator(".market-lanes a.active").evaluate(el => { const s = getComputedStyle(el); return { color: s.color, background: s.backgroundColor }; });
    // The selected pale segment must use the dark ink, not the white button label.
    expect(colors.color).not.toBe("rgb(255, 255, 255)");
    expect(colors.color).not.toBe(colors.background);
    await noOverflow(page);
    await captureViewport(page, testInfo.outputPath(`catalogue-${theme}.png`));
  }
  if (isMobile) {
    expect(await page.locator(".market-search input").evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
    expect((await favorite.boundingBox())!.width).toBeGreaterThanOrEqual(44);
    const menu = page.getByRole("button", { name: "Открыть навигацию", exact: true });
    await menu.tap();
    await expect(page.getByRole("navigation", { name: "Навигация по сайту", exact: true })).toBeVisible();
  }
  await page.getByRole("textbox", { name: "Поиск по маркетплейсу" }).fill("Кабель");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page).toHaveURL(/\/catalog\?q=/);
  await expect(page.locator(".market-product")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("guidance materials, posters, form input and account panel work in portrait and landscape", async ({ page, isMobile }, testInfo) => {
  const errors = await prepare(page, true);
  for (const path of ["/knowledge", "/ai-procurement"]) {
    await page.waitForLoadState("networkidle");
    await page.goto(path);
    await expect(page.locator(".hero-object__poster")).toHaveCSS("background-image", /hero-(help|procurement)-light\.png/);
    await expect(page.locator(".guidance-hero")).toBeVisible();
    const disclosure = page.locator(".guidance-disclosure summary").first();
    await disclosure.click();
    await expect(disclosure.locator("..")).toHaveAttribute("open", "");
    if (isMobile) {
      await expect(page.locator(".hero-object__canvas")).not.toHaveAttribute("data-ready", "true");
      const size = page.viewportSize()!;
      await page.setViewportSize({ width: size.height, height: size.width });
      await noOverflow(page);
      await page.setViewportSize(size);
    }
    await noOverflow(page);
    await captureViewport(page, testInfo.outputPath(path === "/knowledge" ? "help.png" : "ai.png"));
  }
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Открыть личный кабинет", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Меню аккаунта" });
  await expect(drawer).toBeVisible();
  await drawer.getByRole("link", { name: "Настройки", exact: true }).click();
  await expect(drawer).toHaveCount(0);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  expect(errors).toEqual([]);
});

test("MP4 microphone recordings retain their actual container and readable manual fields", async ({ page }) => {
  const errors = await prepare(page, true);
  await page.addInitScript(() => {
    const track = { stop() {} };
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: async () => ({ getTracks: () => [track] }) } });
    class Mp4Recorder {
      static isTypeSupported(type: string) { return type === "audio/mp4"; }
      mimeType = "audio/mp4";
      onstop?: () => void;
      ondataavailable?: (event: { data: Blob }) => void;
      constructor(public stream: MediaStream) {}
      start() {}
      stop() { this.ondataavailable?.({ data: new Blob(["synthetic-mp4-test"], { type: this.mimeType }) }); this.onstop?.(); }
    }
    Object.defineProperty(window, "MediaRecorder", { configurable: true, value: Mp4Recorder });
  });
  let upload = "";
  await page.route("**/api/v1/transcribe", route => {
    upload = route.request().postDataBuffer()!.toString();
    return route.fulfill({ json: { text: "Нужны коробки для отправки" } });
  });
  await page.goto("/needs/new");
  await expect(page.locator("#request_description")).toBeVisible();
  await page.getByRole("button", { name: "Продиктовать запрос", exact: true }).click();
  await page.getByRole("button", { name: "Остановить запись", exact: true }).click();
  await expect(page.locator("#request_description")).toHaveValue("Нужны коробки для отправки");
  expect(upload).toContain("Content-Type: audio/mp4");
  expect(upload).toContain("голосовой-запрос.m4a");
  expect(upload).not.toContain("голосовой-запрос.webm");
  await page.getByRole("button", { name: "Заполнить вручную", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Характеристика 1: название", exact: true })).toHaveValue("Единица заказа");
  await noOverflow(page);
  expect(errors).toEqual([]);
});

test("insufficient shader precision keeps intact CSS glass with working actions", async ({ page }) => {
  const errors = await prepare(page, true);
  await page.addInitScript(() => {
    const precision = WebGLRenderingContext.prototype.getShaderPrecisionFormat;
    WebGLRenderingContext.prototype.getShaderPrecisionFormat = function(shader, type) {
      return type === this.HIGH_FLOAT ? { precision: 10, rangeMin: 14, rangeMax: 14 } as WebGLShaderPrecisionFormat : precision.call(this, shader, type);
    };
  });
  await page.goto("/ai-procurement");
  await expect(page.locator(".guidance-hero .liquid-surface__material")).toBeVisible();
  await expect(page.locator(".guidance-hero")).not.toHaveAttribute("data-mesh-ready", "true");
  await page.getByRole("link", { name: "Создать потребность", exact: true }).first().click();
  await expect(page).toHaveURL(/\/needs\/new$/);
  expect(errors).toEqual([]);
});

test("glass reflection is continuous on both sides of its highlight", async ({ page, isMobile }) => {
  test.skip(isMobile, "Touch intentionally uses the matching static material.");
  await prepare(page);
  await page.addInitScript(() => {
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type: string, ...args: unknown[]) {
      // Test the shell's GPU math separately from the unrelated physical 3D model.
      return type === "webgl2" ? null : Reflect.apply(get, this, [type, ...args]);
    } as typeof HTMLCanvasElement.prototype.getContext;
  });
  await page.goto("/ai-procurement");
  const shell = page.locator(".guidance-hero");
  const supported = await shell.evaluate(el => {
    const gl = el.querySelector<HTMLCanvasElement>(":scope > canvas")!.getContext("webgl");
    const precision = gl?.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
    return Boolean(precision && precision.precision >= 16 && precision.rangeMax >= 62);
  });
  test.skip(!supported, "This runner lacks full-precision WebGL; static fallback is covered separately.");
  await expect(shell).toHaveAttribute("data-mesh-ready", "true", { timeout: 15000 });
  const alpha = await shell.evaluate(el => {
    const canvas = el.querySelector<HTMLCanvasElement>(":scope > canvas")!, gl = canvas.getContext("webgl")!;
    const program = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram;
    gl.uniform2f(gl.getUniformLocation(program, "u_pointer"), 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, gl.getBufferParameter(gl.ARRAY_BUFFER, gl.BUFFER_SIZE) / 8);
    const size = gl.getUniform(program, gl.getUniformLocation(program, "u_size")) as Float32Array;
    const gutter = gl.getUniform(program, gl.getUniformLocation(program, "u_gutter")) as number;
    return [.47, .5, .53].map(y => {
      const pixel = new Uint8Array(4);
      gl.readPixels(Math.round(canvas.width / 2), Math.round((gutter + (size[1] - 2 * gutter) * y) / size[1] * canvas.height), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
      return pixel[3];
    });
  });
  expect(alpha[0]).toBeGreaterThan(10);
  expect(alpha[2]).toBeGreaterThan(10);
  expect(Math.abs(alpha[0] - alpha[2])).toBeLessThanOrEqual(3);
  expect(alpha[1]).toBeGreaterThanOrEqual(Math.max(alpha[0], alpha[2]));
});
