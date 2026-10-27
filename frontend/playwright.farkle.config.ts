import path from 'node:path';
import { defineConfig } from '@playwright/test';

const port = Number(process.env.FARKLE_BROWSER_PORT || 18768);
const site = path.resolve(process.env.FARKLE_SITE_DIR || 'dist-farkle');
export default defineConfig({
  testDir: './tests', testMatch: 'farkle-standalone.spec.ts',
  workers: 1, timeout: 45000, expect: { timeout: 10000 },
  use: { baseURL: `http://127.0.0.1:${port}`, headless: true, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: {
    command: `python -m http.server ${port} --bind 127.0.0.1 --directory "${site}"`,
    url: `http://127.0.0.1:${port}`, timeout: 10000, reuseExistingServer: false,
  },
});
