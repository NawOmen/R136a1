import { expect, test } from "@playwright/test";

const product = { id: "food", name: "Продукты для кухни", category: "Продукты питания", price_rub: "125.50", moq_units: 10, characteristics: {}, price_tiers: [], images: [], company_id: "synthetic-seller" };

test("glass really redraws on hover, rests in idle, and never moves readable content", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/products") ? [product] : [] }));
  // Read back a small GPU region within the draw call; no production counters or preserved buffers.
  await page.addInitScript(() => {
    const draw = WebGLRenderingContext.prototype.drawArrays;
    WebGLRenderingContext.prototype.drawArrays = function(...args) {
      Reflect.apply(draw, this, args);
      const canvas = this.canvas as HTMLCanvasElement;
      const pixels = new Uint8Array(24 * 24 * 4);
      this.readPixels(Math.floor(this.drawingBufferWidth / 2) - 12, Math.floor(this.drawingBufferHeight / 2) - 12, 24, 24, this.RGBA, this.UNSIGNED_BYTE, pixels);
      let hash = 0; for (let i = 0; i < pixels.length; i++) hash = (hash + pixels[i] * (i + 1)) >>> 0;
      canvas.dataset.probePixels = String(hash);
      canvas.dataset.probeDraws = String(Number(canvas.dataset.probeDraws ?? 0) + 1);
    };
  });
  for (const [path, selector] of [["/", ".storefront-hero .liquid-action"], ["/knowledge", ".help-hero"], ["/ai-procurement", ".procurement-hero"]]) {
    await page.goto(path);
    const shell = page.locator(selector), canvas = shell.locator(":scope > .liquid-surface__mesh");
    // Software GPU compilation can queue behind the independent Three.js scene.
    await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
    expect(await canvas.evaluate(c => c.getContext("webgl")!.getContextAttributes()!.premultipliedAlpha)).toBe(true);
    await page.locator(".page-surface").evaluate(async element => { await document.fonts.ready; await Promise.all(element.getAnimations().map(animation => animation.finished)); });
    await page.mouse.move(1, 1);
    await expect.poll(() => canvas.evaluate(c => {
      const gl = c.getContext("webgl")!, p = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram;
      return Array.from(gl.getUniform(p,gl.getUniformLocation(p,"u_pointer")) as Float32Array).map(Math.abs);
    })).toEqual([0, 0]);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const originalPixels = await canvas.getAttribute("data-probe-pixels");
    expect(originalPixels).not.toBe("0");
    const copy = shell.locator(path === "/" ? "a" : "h1").first();
    const before = await copy.boundingBox(), box = (await shell.boundingBox())!;
    await page.mouse.move(box.x + box.width * .88, box.y + box.height * .3);
    await expect(canvas).not.toHaveAttribute("data-probe-pixels", originalPixels!);
    expect(await copy.boundingBox()).toEqual(before);
    expect(await canvas.evaluate(c => c.width <= 1100 && c.height <= 600)).toBe(true);
    await page.mouse.move(1, 1);
    await expect(canvas).toHaveAttribute("data-probe-pixels", originalPixels!, { timeout: 7000 });
    await expect.poll(async () => {
      const count = await canvas.getAttribute("data-probe-draws");
      await page.waitForTimeout(300); // Deliberate idle-work measurement, not a readiness wait.
      return Number(await canvas.getAttribute("data-probe-draws")) - Number(count);
    }).toBe(0);
    await page.getByRole("button", { name: "Включить тёмную тему", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(canvas).not.toHaveAttribute("data-probe-pixels", originalPixels!);
    await page.getByRole("button", { name: "Включить светлую тему", exact: true }).click();
    if (path === "/") {
      await page.goto("/catalog");
      const food = page.getByRole("button", { name: "Продукты питания", exact: true });
      await food.focus(); await page.keyboard.press("Enter");
      await expect(food).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator(".market-product")).toHaveCount(1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator(".liquid-atmosphere canvas")).toHaveCount(0);
  }
});

test("reduced motion, touch and missing WebGL keep usable static glass", async ({ browser }) => {
  for (const mode of ["reduce", "touch", "no-webgl"] as const) {
    const context = await browser.newContext({ baseURL: String(test.info().project.use.baseURL), viewport: { width: 390, height: 844 }, reducedMotion: mode === "reduce" ? "reduce" : "no-preference", hasTouch: mode === "touch", isMobile: mode === "touch" });
    if (mode === "no-webgl") await context.addInitScript(() => {
      const get = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type: string, ...args: unknown[]) {
        return type === "webgl" ? null : Reflect.apply(get, this, [type, ...args]);
      } as typeof get;
    });
    const page = await context.newPage();
    await page.route("**/api/**", route => route.fulfill({ json: [] }));
    await page.goto("/knowledge");
    await expect(page.locator(".help-hero > .liquid-surface__mesh")).not.toHaveAttribute("data-ready", "true");
    await expect(page.getByRole("heading", { name: "Помощь с закупкой", exact: true })).toBeVisible();
    const faq = page.locator(".help-questions summary").first(); await faq.click();
    await expect(page.getByText(/Участник компании включает оба права/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await context.close();
  }
});

test("live reduced-motion changes and GPU context loss fall back, then recover", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/api/**", route => route.fulfill({ json: [] }));
  await page.goto("/ai-procurement");
  const canvas = page.locator(".procurement-hero > .liquid-surface__mesh");
  await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(canvas).not.toHaveAttribute("data-ready", "true", { timeout: 15000 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
  const supported = await canvas.evaluate(c => {
    const extension = c.getContext("webgl")?.getExtension("WEBGL_lose_context");
    if (!extension) return false;
    extension.loseContext(); (c as HTMLCanvasElement & { restore?: () => void }).restore = () => extension.restoreContext(); return true;
  });
  expect(supported).toBe(true);
  await expect(canvas).not.toHaveAttribute("data-ready", "true", { timeout: 15000 });
  await expect(page.getByRole("link", { name: "Создать потребность", exact: true }).first()).toHaveAttribute("href", "/needs/new");
  await canvas.evaluate(c => (c as HTMLCanvasElement & { restore: () => void }).restore());
  await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 15000 });
});


test("dense and forced-color modes keep the solid fallback in both themes", async ({ page }) => {
  await page.route("**/api/**", route => route.fulfill({ json: [] }));
  const session = await page.context().newCDPSession(page);
  for (const theme of ["light", "dark"]) {
    for (const path of ["/knowledge", "/ai-procurement"]) {
      await page.goto(path);
      if (theme === "dark") await page.locator("html").evaluate(el => el.setAttribute("data-theme", "dark"));
      await session.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-transparency", value: "reduce" }] });
      const shell = page.locator(".guidance-hero");
      await expect(shell.locator(":scope > .liquid-surface__mesh")).not.toHaveAttribute("data-ready", "true");
      expect(await shell.locator(".liquid-surface__material").evaluate(el => {
        const color = getComputedStyle(el).backgroundColor;
        return color.startsWith("rgb(") && getComputedStyle(el).backdropFilter === "none";
      })).toBe(true);
      await page.emulateMedia({ forcedColors: "active" });
      await expect(shell.locator(":scope > .liquid-surface__mesh")).not.toHaveAttribute("data-ready", "true");
      await expect(page.locator("main h1")).toBeVisible();
      await page.emulateMedia({ forcedColors: "none" });
      await session.send("Emulation.setEmulatedMedia", { features: [] });
    }
  }
});


test("responsive corners have one source and the active mesh owns the bright edge", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/api/**", route => route.fulfill({ json: [] }));
  for (const path of ["/knowledge", "/ai-procurement"]) {
    await page.goto(path);
    for (const theme of ["light", "dark"]) for (const width of [1440, 761, 760, 390]) {
      await page.locator("html").evaluate((el, value) => el.setAttribute("data-theme", value), theme);
      await page.setViewportSize({ width, height: 900 });
      const shell = page.locator(".guidance-hero");
      await expect(shell).toHaveAttribute("data-mesh-ready", "true");
      const cssCorners = await shell.evaluate(el => {
        const style = getComputedStyle(el);
        return [style.borderTopLeftRadius, style.borderTopRightRadius, style.borderBottomRightRadius, style.borderBottomLeftRadius].map(parseFloat);
      });
      await expect.poll(() => shell.evaluate(el => {
        const canvas = el.querySelector(":scope > canvas")!, gl = canvas.getContext("webgl")!;
        const program = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram;
        return Array.from(gl.getUniform(program, gl.getUniformLocation(program, "u_radii")) as Float32Array);
      }), { message: `${path}, ${theme}, ${width}px: mesh corners follow CSS`, timeout: 15000 }).toEqual(cssCorners);
      expect(await shell.locator(".liquid-surface__material").evaluate(el => getComputedStyle(el).boxShadow.includes("inset"))).toBe(false);
    }
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(page.locator(".guidance-hero")).not.toHaveAttribute("data-mesh-ready", "true");
    expect(await page.locator(".guidance-hero .liquid-surface__material").evaluate(el => getComputedStyle(el).boxShadow.includes("inset"))).toBe(true);
    await page.emulateMedia({ reducedMotion: "no-preference" });
  }
});

test("bent hero edges retain a transparent guard band at pointer extremes", async ({ page }) => {
  test.setTimeout(90000); // GPU readback across both themes, two widths and both hero surfaces.
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/api/**", route => route.fulfill({ json: [] }));
  await page.addInitScript(() => {
    const draw = WebGLRenderingContext.prototype.drawArrays;
    WebGLRenderingContext.prototype.drawArrays = function(...args) {
      Reflect.apply(draw, this, args);
      const canvas = this.canvas as HTMLCanvasElement;
      if (!canvas.dataset.probeEdges) return;
      const wanted = JSON.parse(canvas.dataset.probeEdges) as { x: number; y: number; id: string };
      const program = this.getParameter(this.CURRENT_PROGRAM) as WebGLProgram;
      const pointer = this.getUniform(program,this.getUniformLocation(program,"u_pointer")) as Float32Array;
      if (Math.abs(pointer[0]-wanted.x) > .025 || Math.abs(pointer[1]-wanted.y) > .025) return;
      delete canvas.dataset.probeEdges;
      const w = this.drawingBufferWidth, h = this.drawingBufferHeight, pixels = new Uint8Array(w * h * 4);
      this.readPixels(0, 0, w, h, this.RGBA, this.UNSIGNED_BYTE, pixels);
      let left = w, right = -1, top = h, bottom = -1;
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (pixels[(y * w + x) * 4 + 3] > 8) {
        left = Math.min(left,x); right = Math.max(right,x); top = Math.min(top,y); bottom = Math.max(bottom,y);
      }
      canvas.dataset.edgeBounds = JSON.stringify({ left, right, top, bottom, w, h, id:wanted.id });
    };
  });
  for (const path of ["/knowledge", "/ai-procurement"]) {
    await page.goto(path);
    const shell = page.locator(".guidance-hero"), canvas = shell.locator(":scope > .liquid-surface__mesh");
    await expect(canvas).toHaveAttribute("data-ready", "true");
    for (const width of [1600, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const theme of ["light", "dark"]) {
        await page.locator("html").evaluate((el, value) => el.setAttribute("data-theme", value), theme);
        for (const [x,y] of [[.99,.5],[.94,.14],[.94,.86],[.01,.5]]) {
          const box = (await shell.boundingBox())!;
          const id = `${path}:${width}:${theme}:${x}:${y}`;
          await canvas.evaluate((c,point)=>{c.dataset.probeEdges=JSON.stringify(point);},{x:x*2-1,y:-(y*2-1),id});
          await page.mouse.move(box.x + box.width * x, box.y + box.height * y);
          await expect.poll(() => canvas.evaluate(c=>{
            const gl=c.getContext("webgl")!,p=gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram;
            return {id:c.dataset.edgeBounds?JSON.parse(c.dataset.edgeBounds).id:null,pointer:Array.from(gl.getUniform(p,gl.getUniformLocation(p,"u_pointer")) as Float32Array),wanted:c.dataset.probeEdges};
          }), {message:id}).toMatchObject({id});
          const bounds = JSON.parse((await canvas.getAttribute("data-edge-bounds"))!);
          expect(bounds.right).toBeGreaterThan(bounds.left);
          expect(bounds.bottom).toBeGreaterThan(bounds.top);
          expect(Math.min(bounds.left,bounds.top,bounds.w - 1 - bounds.right,bounds.h - 1 - bounds.bottom)).toBeGreaterThanOrEqual(3);
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        }
      }
    }
  }
});

test("solid category buttons gently grow without glass and preserve filtering", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const assortment = [product, { ...product, id: "packaging", name: "Коробки", category: "Упаковка и тара" }, { ...product, id: "business", name: "Рабочая одежда", category: "Товары для бизнеса" }];
  await page.route("**/api/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/products") ? assortment : [] }));
  await page.goto("/catalog");
  const rail = page.getByRole("complementary", { name: "Категории товаров" });
  await expect(rail.locator("canvas,.liquid-surface__material")).toHaveCount(0);
  for (const name of ["Все категории","Упаковка и тара","Товары для бизнеса"]) {
    const button = rail.getByRole("button",{name,exact:true});
    await page.mouse.move(1,1);
    const resting = (await button.boundingBox())!;
    await button.hover();
    await expect.poll(async()=>((await button.boundingBox())!.width/resting.width)).toBeGreaterThan(1.01);
    expect((await button.boundingBox())!.width/resting.width).toBeLessThanOrEqual(1.04);
    await page.mouse.move(1,1);
    await expect.poll(async()=>Math.abs((await button.boundingBox())!.width-resting.width)).toBeLessThan(.1);
  }
  await page.setViewportSize({width:390,height:844});
  const business = rail.getByRole("button",{name:"Товары для бизнеса",exact:true});
  await business.focus(); await page.keyboard.press("Enter");
  await expect(page.locator(".market-product")).toHaveCount(1);
  expect(await page.locator(".market-product").innerText()).toContain("Рабочая одежда");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.emulateMedia({reducedMotion:"reduce"});
  await business.hover();
  expect(await business.evaluate(el=>getComputedStyle(el).transform)).toBe("none");
  await rail.getByRole("button",{name:"Все категории",exact:true}).click();
  await expect(page.locator(".market-product")).toHaveCount(3);
});
