import { mkdir } from "node:fs/promises";
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
const outputDir = path.resolve("docs", "assets");
const outputPath = path.join(outputDir, "paga-eval-demo.webm");
await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1080 },
  recordVideo: { dir: outputDir, size: { width: 1440, height: 1080 } },
});
const page = await context.newPage();
const pause = (milliseconds) => page.waitForTimeout(milliseconds);

async function runScenario(preset, readingTime = 3500) {
  await page.click(`[data-preset="${preset}"]`);
  await pause(800);
  await page.click("#evaluate");
  await page.waitForFunction(() => !document.querySelector("#evaluate").disabled);
  await pause(readingTime);
}

await page.goto(demoUrl, { waitUntil: "networkidle" });
await page.waitForSelector("#evaluate");
await pause(2500);
await runScenario("supportive");
await runScenario("overcorrect");
await runScenario("review");
await runScenario("decode");
await page.click("#update-profile");
await page.waitForFunction(() => !document.querySelector("#update-profile").disabled);
await pause(2200);
await page.click("#lookup-profile");
await page.waitForFunction(() => !document.querySelector("#lookup-profile").disabled);
await pause(3500);

const video = page.video();
await context.close();
await video.saveAs(outputPath);
await browser.close();

console.log(`Recorded ${outputPath}`);
