/** Render transparent, matching first frames from the actual live 3D scenes. No image service. */
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../tests/e2e/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const base = new URL(process.argv[2] || "http://localhost:3000");
if (!["localhost", "127.0.0.1", "[::1]"].includes(base.hostname)) throw new Error("Use a local project preview");
const root = new URL("../", import.meta.url), sources = {};
const hash = buffer => createHash("sha256").update(buffer).digest("hex");
for (const source of ["apps/web/app/components/heroObjectModels.ts", "apps/web/app/components/heroObjectScene.ts"]) {
  sources[source] = hash(await readFile(new URL(source, root)));
}
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 946 }, deviceScaleFactor: 1.6, reducedMotion: "no-preference" });
  await page.addInitScript(() => {
    localStorage.setItem("porukam-theme", "light");
    // Capture in the same task as the completed render, before the browser discards its buffer.
    const draw = WebGL2RenderingContext.prototype.drawElements;
    WebGL2RenderingContext.prototype.drawElements = function(...args) {
      Reflect.apply(draw, this, args);
      const canvas = this.canvas;
      if (!(canvas instanceof HTMLCanvasElement) || !canvas.matches(".hero-object__canvas") || !canvas.dataset.capturePoster || canvas.dataset.captureQueued) return;
      canvas.dataset.captureQueued = "true";
      queueMicrotask(() => {
        canvas.dataset.posterResult = canvas.toDataURL("image/png");
        delete canvas.dataset.capturePoster; delete canvas.dataset.captureQueued;
      });
    };
  });
  for (const [kind, route] of [["help", "/knowledge"], ["procurement", "/ai-procurement"]]) {
    await page.goto(new URL(route, base).href);
    const canvas = page.locator(".hero-object__canvas");
    await expect(canvas).toHaveAttribute("data-ready", "true", { timeout: 30000 });
    await page.mouse.move(1, 1);
    for (const theme of ["dark", "light"]) {
      await canvas.evaluate(element => { element.dataset.capturePoster = "true"; });
      await page.locator("html").evaluate((element, theme) => { element.dataset.theme = theme; }, theme);
      await expect(canvas).toHaveAttribute("data-poster-result", /^data:image\/png;base64,/, { timeout: 30000 });
      const png = Buffer.from((await canvas.getAttribute("data-poster-result")).split(",")[1], "base64");
      const filename = `hero-${kind}-${theme}.png`, target = new URL(`apps/web/public/images/${filename}`, root);
      await writeFile(target, png);
      await writeFile(new URL(`${target.href}.json`), JSON.stringify({
        origin: "Transparent first frame rendered from the project's own procedural Three.js scene; matches live geometry, pose, camera, lighting and theme. No external image generation or old illustration.",
        generator: "scripts/render-hero-posters.mjs", kind, theme,
        sources, dimensions: [png.readUInt32BE(16), png.readUInt32BE(20)],
        colorSpace: "sRGB", transparentBackground: true, sha256: hash(png), bytes: png.length,
      }, null, 2) + "\n");
      await canvas.evaluate(element => { delete element.dataset.posterResult; });
      console.log(`${fileURLToPath(target)} (${png.length} bytes)`);
    }
  }
} finally { await browser.close(); }
