import { defineConfig } from 'playwright/test';
export default defineConfig({
  testDir: './visual-tests', workers: 1, retries: 0, timeout: 60000,
  outputDir: 'test-results/vehicle-photos', reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:14221', headless: true, serviceWorkers: 'block', screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: process.env.SIGRA_PHOTO_LOCAL_SERVER_STARTED === 'true' ? undefined : { command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 14221 --strictPort',
    url: 'http://127.0.0.1:14221', reuseExistingServer: false,
    env: { VITE_API_URL: '/sigra-api', VITE_PUBLIC_DEMO_MODE: 'false', VITE_ACADEMIC_TEST_MODE: 'false' } },
});
