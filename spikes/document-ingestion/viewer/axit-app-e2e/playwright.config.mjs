import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../../../..");
const baseURL = process.env.AXIT_N4_BASE_URL;
if (!baseURL) throw new Error("AXIT_N4_BASE_URL is required");
const parsed = new URL(baseURL);
if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1") {
  throw new Error("AXIT_N4_BASE_URL must be an isolated http://127.0.0.1 URL");
}

export default defineConfig({
  testDir: here,
  testMatch: "notification-audit-settings.spec.mjs",
  outputDir: path.join(root, ".omx/state/notification-audit-settings/playwright-results"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["line"], [path.join(here, "evidence-reporter.mjs")]],
  timeout: 120_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    viewport: { width: 1440, height: 1100 },
    serviceWorkers: "block",
    trace: "on",
  },
});
