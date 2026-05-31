import { mkdir, readdir, unlink } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const appData = process.env.APPDATA;
if (!appData) {
  throw new Error("APPDATA is required to locate the global Playwright install.");
}

const playwrightModule = path.join(
  appData,
  "npm",
  "node_modules",
  "playwright",
  "index.mjs",
);
const { chromium } = await import(pathToFileURL(playwrightModule).href);

const demoUrl = process.env.PAGA_DEMO_URL ?? "http://127.0.0.1:8000/demo";
const screenshotDir = path.resolve("docs", "assets", "screenshots");
const videoDir = path.resolve("docs", "assets");
const outputPath = path.join(videoDir, "paga-eval-showcase.webm");
await mkdir(screenshotDir, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const pause = milliseconds => page.waitForTimeout(milliseconds);

async function screenshot(name) {
  await page.screenshot({ path: path.join(screenshotDir, name), fullPage: true });
}

async function runScenario(preset) {
  await page.click(`[data-preset="${preset}"]`);
  await page.click("#evaluate");
  await page.waitForFunction(() => !document.querySelector("#evaluate").disabled);
  await pause(500);
}

await page.goto(demoUrl, { waitUntil: "networkidle" });
await page.waitForSelector("#evaluate");
await page.waitForFunction(() => document.querySelector("#mode-banner").textContent.startsWith("Connected"));
await screenshot("01-console-overview.png");
await runScenario("overcorrect");
await screenshot("02-over-intervention.png");
await runScenario("review");
await screenshot("03-human-review.png");
await runScenario("decode");
await screenshot("04-privacy-operations.png");
await page.close();

const showcaseUrl = pathToFileURL(path.resolve("docs", "showcase_video.html")).href;
const context = await browser.newContext({
  viewport: { width: 1600, height: 900 },
  recordVideo: { dir: videoDir, size: { width: 1600, height: 900 } },
});
const showcase = await context.newPage();
await showcase.goto(showcaseUrl, { waitUntil: "load" });
const durations = [5200, 6200, 6200, 6500, 6500, 6500, 6200];
for (let index = 0; index < durations.length; index += 1) {
  await showcase.evaluate(sceneIndex => window.showScene(sceneIndex), index);
  if (index === 1) {
    await showcase.screenshot({ path: path.join(screenshotDir, "05-architecture.png") });
  }
  if (index === 2) {
    await showcase.screenshot({ path: path.join(screenshotDir, "06-executive-dashboard.png") });
  }
  await showcase.waitForTimeout(durations[index]);
}

const video = showcase.video();
await context.close();
await video.saveAs(outputPath);
await browser.close();

for (const filename of await readdir(videoDir)) {
  if (filename.startsWith("page@") && filename.endsWith(".webm")) {
    await unlink(path.join(videoDir, filename));
  }
}

console.log(`Captured screenshots in ${screenshotDir}`);
console.log(`Recorded ${outputPath}`);
