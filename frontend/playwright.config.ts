import { defineConfig } from '@playwright/test';

const port = Number(process.env.WORKBENCH_BROWSER_PORT || 18767);
export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 45000,
  expect: { timeout: 10000 },
  use: { baseURL: `http://127.0.0.1:${port}`, headless: true, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: {
    command: `uv run --no-sync python -m tests.presentation_smoke_server --port ${port}`,
    cwd: '..',
    url: `http://127.0.0.1:${port}/api/health`,
    timeout: 30000,
    reuseExistingServer: false,
  },
});
