import { expect, test } from "@playwright/test";

// Software WebGL can spend time compiling physical glass materials on CI.
test.setTimeout(120_000);

test("first paint shows the current model even while the 3D JavaScript is delayed", async ({ browser }) => {
  for (const [path, kind] of [["/knowledge", "help"], ["/ai-procurement", "procurement"]]) {
    const context = await browser.newContext({ baseURL: String(test.info().project.use.baseURL), viewport: { width: 1440, height: 946 } });
    const page = await context.newPage(), oldImages: string[] = [];
    page.on("request", request => { if (/\/(business-link|procurement-help)\.webp/.test(request.url())) oldImages.push(request.url()); });
    let release = () => {};
    const scripts = new Promise<void>(resolve => { release = resolve; });
    await page.route(url => url.pathname.startsWith("/_next/static/chunks/") && url.pathname.endsWith(".js"), async route => { await scripts; await route.continue(); });
    try {
      await page.goto(path, { waitUntil: "commit" });
      const art = page.locator(".hero-object"), canvas = art.locator("canvas"), poster = art.locator(".hero-object__poster");
      await expect(poster).toBeVisible();
      await page.locator(".page-surface").evaluate(async element => {
        await document.fonts.ready;
        await Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished));
      });
      const before = await art.boundingBox();
      expect(await poster.evaluate(async element => {
        const url = getComputedStyle(element).backgroundImage.slice(5, -2);
        const image = new Image(); image.src = url; await image.decode();
        return { url, width: image.naturalWidth };
      })).toEqual({ url: expect.stringContaining(`/images/hero-${kind}-light.png`), width: expect.any(Number) });
      await expect(art.locator("img")).toHaveCount(0);
      await expect(canvas).not.toHaveAttribute("data-ready", "true");
      expect(oldImages).toEqual([]);
      release();
      await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 30000 });
      await expect(poster).toBeHidden();
      expect(await art.boundingBox()).toEqual(before);
      expect(oldImages).toEqual([]);
    } finally { release(); await context.close(); }
  }
});

test("hero meshes follow the pointer in 3D, return, and stop drawing at rest", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 946 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/api/**", route => route.fulfill({ json: [] }));
  page.on("pageerror", error => { throw error; });
  // Test-only evidence from real geometry draws, without production debug hooks or animation loops.
  await page.addInitScript(() => {
    const draw = WebGL2RenderingContext.prototype.drawElements;
    WebGL2RenderingContext.prototype.drawElements = function(...args) {
      Reflect.apply(draw, this, args);
      const canvas = this.canvas as HTMLCanvasElement;
      if (!canvas.classList.contains("hero-object__canvas")) return;
      canvas.dataset.probeDraws = String(Number(canvas.dataset.probeDraws ?? 0) + 1);
      const program = this.getParameter(this.CURRENT_PROGRAM) as WebGLProgram;
      const location = this.getUniformLocation(program, "modelViewMatrix");
      if (location) canvas.dataset.probeMatrix = JSON.stringify(Array.from(this.getUniform(program, location) as Float32Array));
    };
  });
  for (const path of ["/ai-procurement", "/knowledge"]) {
    await page.goto(path);
    const art = page.locator(".hero-object"), canvas = art.locator("canvas");
    await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
    await expect(art.locator(".hero-object__poster")).toBeHidden();
    await page.mouse.move(1, 1);
    await expect.poll(() => canvas.getAttribute("data-probe-matrix")).not.toBeNull();
    const original = await canvas.getAttribute("data-probe-matrix");
    const copy = await page.locator(".guidance-hero__copy").boundingBox(), box = (await art.boundingBox())!;
    await page.mouse.move(box.x + box.width * .92, box.y + box.height * .22);
    await expect(canvas).not.toHaveAttribute("data-probe-matrix", original!);
    // Horizontal and vertical pointer positions produce different actual mesh transforms.
    const right = await canvas.getAttribute("data-probe-matrix");
    await page.mouse.move(box.x + box.width * .12, box.y + box.height * .85);
    await expect(canvas).not.toHaveAttribute("data-probe-matrix", right!);
    expect(await page.locator(".guidance-hero__copy").boundingBox()).toEqual(copy);
    expect(await canvas.evaluate(c => c.width <= 640 && c.height <= 640)).toBe(true);
    await page.mouse.move(1, 1);
    await expect(canvas).toHaveAttribute("data-probe-matrix", original!, { timeout: 7000 });
    await expect.poll(async () => {
      const count = await canvas.getAttribute("data-probe-draws");
      await page.waitForTimeout(300); // Deliberate idle-work measurement.
      return Number(await canvas.getAttribute("data-probe-draws")) - Number(count);
    }).toBe(0);
    await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
    await page.getByRole("button", { name: "Включить светлую тему", exact: true }).click();
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(canvas).not.toHaveAttribute("data-ready", "true", { timeout: 15000 });
    await expect(art.locator(".hero-object__poster")).toBeVisible();
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
  }
});

test("hero illustrations survive touch, no WebGL2, forced colors and context loss", async ({ browser }) => {
  for (const mode of ["touch", "no-webgl", "forced-colors"] as const) {
    const context = await browser.newContext({ baseURL: String(test.info().project.use.baseURL), viewport: { width: 390, height: 844 }, hasTouch: mode === "touch", isMobile: mode === "touch", forcedColors: mode === "forced-colors" ? "active" : "none" });
    if (mode === "no-webgl") await context.addInitScript(() => {
      const get = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type: string, ...args: unknown[]) {
        return type === "webgl2" ? null : Reflect.apply(get, this, [type, ...args]);
      } as typeof get;
    });
    const page = await context.newPage();
    await page.route("**/api/**", route => route.fulfill({ json: [] }));
    for (const path of ["/knowledge", "/ai-procurement"]) {
      await page.goto(path);
      const art = page.locator(".hero-object");
      if (mode === "forced-colors") await expect(page.locator(".guidance-art")).toBeHidden();
      else await expect(art.locator(".hero-object__poster")).toBeVisible();
      await expect(art.locator("canvas")).not.toHaveAttribute("data-ready", "true", { timeout: 15000 });
      await expect(page.locator(".guidance-hero h1")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await context.close();
  }
  const context = await browser.newContext({ baseURL: String(test.info().project.use.baseURL), viewport: { width: 1440, height: 946 } });
  const page = await context.newPage();
  await page.route("**/api/**", route => route.fulfill({ json: [] }));
  await page.goto("/knowledge");
  const canvas = page.locator(".hero-object canvas");
  await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
  expect(await canvas.evaluate(c => {
    const extension = c.getContext("webgl2")!.getExtension("WEBGL_lose_context");
    if (!extension) return false;
    (c as HTMLCanvasElement & { restore: () => void }).restore = () => extension.restoreContext();
    extension.loseContext(); return true;
  })).toBe(true);
  await expect(canvas).not.toHaveAttribute("data-ready", "true", { timeout: 15000 });
  await expect(page.locator(".hero-object__poster")).toBeVisible();
  await canvas.evaluate(c => (c as HTMLCanvasElement & { restore: () => void }).restore());
  await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
  await page.getByRole("link", { name: "Создать потребность", exact: true }).first().focus();
  await expect(page.getByRole("link", { name: "Создать потребность", exact: true }).first()).toBeFocused();
  await context.close();
});
