import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "playwright/test";
import {
  prepareE2EEnvironment,
  reusePreparedE2EEnvironment,
} from "./e2e/environment.js";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(frontendDir, "..");
const backendDir = path.join(rootDir, "backend");
const localPython = path.join(backendDir, ".venv", "Scripts", "python.exe");
const pythonBin = process.env.SIGRA_PYTHON_BIN
  || (process.platform === "win32" && fs.existsSync(localPython) ? localPython : "python");
const backendPort = Number(process.env.SIGRA_E2E_BACKEND_PORT || 8010);
const frontendPort = Number(process.env.SIGRA_E2E_FRONTEND_PORT || 4183);
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const e2eEnvironment = process.env.SIGRA_E2E_DATABASE_PATH
  ? reusePreparedE2EEnvironment({
    rootDir,
    databasePath: process.env.SIGRA_E2E_DATABASE_PATH,
  })
  : prepareE2EEnvironment({ rootDir });
process.env.SIGRA_E2E_DATABASE_PATH = e2eEnvironment.databasePath;

export default defineConfig({
  testDir: "./e2e",
  globalTeardown: "./e2e/global-teardown.js",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  outputDir: "test-results/e2e",
  reporter: "line",
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: `"${pythonBin}" -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: backendDir,
      env: {
        ...process.env,
        DATABASE_URL: e2eEnvironment.databaseUrl,
        CORS_ALLOWED_ORIGINS: frontendUrl,
        FIPE_AUTO_REFRESH: "false",
        PYTHONUTF8: "1",
      },
      url: `${backendUrl}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "node e2e/start-frontend.mjs",
      cwd: frontendDir,
      env: {
        ...process.env,
        VITE_API_URL: backendUrl,
        SIGRA_E2E_BACKEND_HEALTH_URL: `${backendUrl}/health`,
        SIGRA_E2E_FRONTEND_PORT: String(frontendPort),
      },
      url: frontendUrl,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
