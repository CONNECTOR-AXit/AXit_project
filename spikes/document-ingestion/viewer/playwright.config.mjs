import { defineConfig } from "@playwright/test";

const baseURL = "http://127.0.0.1:4173";
const channel = process.env.AXIT_PLAYWRIGHT_CHANNEL;

export default defineConfig({
  testDir: "./tests",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  timeout: 20_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL,
    browserName: "chromium",
    ...(channel ? { channel } : {}),
    headless: true,
    viewport: { width: 1440, height: 1100 },
    deviceScaleFactor: 1,
    serviceWorkers: "block",
    trace: "retain-on-failure"
  },
  webServer: {
    command: "node server.mjs --port 4173",
    url: `${baseURL}/healthz`,
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
    timeout: 15_000
  }
});
