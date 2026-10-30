import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { navigateSettings, answerConfirmation } from './controls';
import type { WebFilterSettings } from '../src/types/tools';

const defaults = ['youtube.com', 'instagram.com', 'facebook.com', 'tiktok.com', 'flipboard.com', 'fb.watch', 'baidu.com', 'ifeng.com']
  .map((host) => `*://*.${host}/*`).join('\n');
const custom = '# Custom\n*://*.blocked.example/*\n@*://safe.blocked.example/*';

for (const locale of ['en', 'zh-CN']) {
  const words = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/settings.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) test.describe(`Web filters ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    test.beforeEach(async ({ page, request }) => {
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      await request.post('/__test__/web-filter-source', { data: { reset: true } });
      await request.patch('/api/tools/web/filters', { data: { custom_rules: defaults } });
      await request.patch('/api/tools/web/settings', { data: { max_results: 5 } });
      const state: WebFilterSettings = await (await request.get('/api/tools/web/filters')).json();
      for (const row of state.subscriptions) {
        if (!row.id.startsWith('default-')) await request.delete(`/api/tools/web/subscriptions/${row.id}`);
        else await request.patch(`/api/tools/web/subscriptions/${row.id}`, { data: { enabled: true } });
      }
      await page.goto('/settings?tab=tools&view=web');
    });

    test('saves custom rules, reports invalid lines and preserves an explicit empty list', async ({ page, request }, info) => {
      const area = page.getByRole('textbox', { name: words.webFilters.custom, exact: true });
      const region = page.getByRole('region', { name: words.webFilters.custom, exact: true });
      await expect(area).toHaveValue(defaults);
      await expect(area).toHaveCSS('color', await page.locator('body').evaluate((node) => getComputedStyle(node).color));
      await expect(page.locator('[data-subscription-id]')).toHaveCount(4);
      await area.fill(custom);
      await region.getByRole('button', { name: words.save, exact: true }).click();
      await expect.poll(async () => (await (await request.get('/api/tools/web/filters')).json()).custom_rules).toBe(custom);
      await page.reload();
      await expect(area).toHaveValue(custom);
      await area.fill('# Custom\n/unsupported/');
      await region.getByRole('button', { name: words.save, exact: true }).click();
      await expect(region.getByRole('alert')).toContainText(words.webFilters.invalidRule.replace('{{line}}', '2'));
      await expect(area).toHaveAttribute('aria-invalid', 'true');
      expect((await (await request.get('/api/tools/web/filters')).json()).custom_rules).toBe(custom);
      await page.screenshot({ path: info.outputPath('invalid-rule.png'), fullPage: true });
      await area.fill('');
      await region.getByRole('button', { name: words.save, exact: true }).click();
      await expect.poll(async () => (await (await request.get('/api/tools/web/filters')).json()).custom_rules).toBe('');
      await page.reload();
      await expect(area).toHaveValue('');
    });

    test('manages subscriptions without overwriting custom drafts and retains failed refreshes', async ({ page, request }, info) => {
      const area = page.getByRole('textbox', { name: words.webFilters.custom, exact: true });
      await expect(area).toHaveValue(defaults);
      await area.fill(custom);
      await page.getByRole('button', { name: words.webFilters.add, exact: true }).click();
      const dialog = page.getByRole('dialog', { name: words.webFilters.add, exact: true });
      await dialog.getByLabel(words.webFilters.name, { exact: true }).fill('Custom filter');
      await dialog.getByLabel(words.webFilters.url, { exact: true }).fill('https://filters.example/browser.txt');
      await dialog.getByRole('button', { name: words.webFilters.add, exact: true }).click();
      await expect(dialog).toBeHidden();
      const row = page.getByRole('group', { name: 'Custom filter', exact: true });
      await expect(row).toBeVisible();
      const id = (await row.getAttribute('data-subscription-id'))!;
      const readRow = async () => ((await (await request.get('/api/tools/web/filters')).json()) as WebFilterSettings)
        .subscriptions.find((item) => item.id === id)!;
      const updated = (await readRow()).last_success_at;
      await row.getByRole('switch').click();
      await expect(row.getByRole('switch')).not.toBeChecked();
      await row.getByRole('button', { name: words.webFilters.update.replace('{{name}}', 'Custom filter') }).click();
      await expect.poll(async () => (await readRow()).last_success_at).not.toBe(updated);
      await expect(area).toHaveValue(custom);
      const successful = (await readRow()).last_success_at;
      await request.post('/__test__/web-filter-source', { data: { url: 'https://filters.example/browser.txt', error: true } });
      await row.getByRole('button', { name: words.webFilters.update.replace('{{name}}', 'Custom filter') }).click();
      await expect(row.getByRole('alert')).toHaveText(words.webFilters.downloadFailed);
      expect((await readRow()).last_success_at).toBe(successful);
      expect((await readRow()).rule_count).toBe(1);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath('subscription-error.png'), fullPage: true });
      await row.getByRole('button', { name: words.webFilters.delete.replace('{{name}}', 'Custom filter') }).click();
      await answerConfirmation(page, true, locale);
      await expect(row).toHaveCount(0);
      await expect(area).toHaveValue(custom);
    });

    test('guards both forms across the new Tools subpages', async ({ page }) => {
      const area = page.getByRole('textbox', { name: words.webFilters.custom, exact: true });
      const count = page.getByLabel(words.webTools.maxResults, { exact: true });
      await expect(area).toHaveValue(defaults);
      await count.fill('6');
      await navigateSettings(page, words.tools, words.toolGroups.qqbot);
      await answerConfirmation(page, false, locale);
      await expect(page).toHaveURL('/settings?tab=tools&view=web');
      await expect(count).toHaveValue('6');
      if (width < 768) await page.keyboard.press('Escape');
      await count.fill('5');
      await area.fill(custom);
      await navigateSettings(page, words.tools, words.toolGroups.qqbot);
      await answerConfirmation(page, false, locale);
      if (width < 768) await page.keyboard.press('Escape');
      await expect(area).toHaveValue(custom);
      await navigateSettings(page, words.tools, words.toolGroups.qqbot);
      await answerConfirmation(page, true, locale);
      await expect(page).toHaveURL('/settings?tab=tools&view=qqbot');
      await expect(page.locator('[data-tool-name^="qq_"]')).toHaveCount(4);
      await page.goBack();
      await expect(page).toHaveURL('/settings?tab=tools&view=web');
      await expect(area).toHaveValue(defaults);
      await expect(count).toHaveValue('5');
    });
  });
}

