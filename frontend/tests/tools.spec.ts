import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const words = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/settings.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`Tools catalog ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });

      test('groups the complete read-only catalog without a session', async ({ page, request }, info) => {
        const errors: string[] = [];
        const requests: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        page.on('request', (request) => {
          if (new URL(request.url()).pathname.startsWith('/api/tools')) requests.push(`${request.method()} ${new URL(request.url()).pathname}`);
        });
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        // The browser server also registers a synthetic tool for approval tests.
        const catalog = (await (await request.get('/api/tools')).json()).filter((tool: { name: string }) => !tool.name.startsWith('test_'));
        expect(catalog).toHaveLength(6);
        await request.patch('/api/tools/web/settings', { data: { api_key: '' } });
        await page.route('**/api/tools', (route) => route.fulfill({ json: catalog }));
        await page.route('**/api/sessions', (route) => route.fulfill({ json: [] }));
        await page.goto('/settings?tab=tools');

        const panel = page.getByRole('region', { name: words.toolCatalog, exact: true });
        const general = panel.getByRole('region', { name: words.toolGroups.general, exact: true });
        const qq = panel.getByRole('region', { name: words.toolGroups.qqbot, exact: true });
        await expect(general.locator('[data-slot="item-title"]')).toHaveText(['web_fetch', 'web_search']);
        await expect(qq.locator('[data-slot="item-title"]')).toHaveText(['qq_generate_image', 'qq_send_image', 'qq_send_message', 'qq_skip_reply']);
        await expect(panel.locator('[data-slot="separator"]')).toHaveCount(2);
        await expect(panel.locator('input[type="password"]')).toHaveCount(1);
        await expect(panel.locator('.tool-output, .tool-search-settings, .tool-call-form')).toHaveCount(0);
        await expect(panel.getByRole('button', { name: words.toolSchema, exact: true })).toHaveCount(6);
        await expect(panel.locator('[data-slot="code-block-content"]')).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('tools-catalog.png'), fullPage: true });
        for (const tool of catalog) {
          const item = panel.locator(`[data-tool-name="${tool.name}"]`);
          await expect(item).toContainText(words.toolDescriptions[tool.name]);
          const trigger = item.getByRole('button', { name: words.toolSchema, exact: true });
          await expect(trigger).toHaveAttribute('aria-expanded', 'false');
          await trigger.focus();
          await trigger.press('Enter');
          await expect(item.locator('[data-slot="code-block-content"]')).toHaveText(JSON.stringify(tool.parameters, null, 2));
          await trigger.press('Space');
          await expect(trigger).toHaveAttribute('aria-expanded', 'false');
        }
        await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect([...new Set(requests)].sort()).toEqual(['GET /api/tools', 'GET /api/tools/web/settings']);
        expect(errors).toEqual([]);
      });
    });
  }
}
