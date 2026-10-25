import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`HTTP LAN browser APIs ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('uploads and sends without secure-context UUID support', async ({ page, request }) => {
      const labels = words(locale, 'personas'), llm = words(locale, 'llm');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((language) => {
        localStorage.setItem('cogita.locale', language);
        Object.defineProperty(crypto, 'randomUUID', { value: undefined });
      }, locale);
      await page.goto('/new');
      await page.locator('.composer textarea').fill('HTTP LAN attachment');
      await page.locator('.composer input[type=file]').setInputFiles({ name: 'lan.txt', mimeType: 'text/plain', buffer: Buffer.from('LAN upload') });
      await expect(page.locator('.upload-ready')).toHaveCount(1);
      await page.locator('.composer').getByRole('button', { name: labels.send, exact: true }).click();
      await expect(page.locator('.reply-answer')).toContainText('Browser final answer.');
      await expect(page.locator('.message-row.user')).toContainText('lan.txt');
      await page.reload();
      await expect(page.locator('.reply-answer')).toContainText('Browser final answer.');
      await page.goto('/settings?tab=models');
      await page.getByRole('button', { name: llm.generateKey, exact: true }).click();
      await expect(page.getByLabel(llm.apiKey, { exact: true })).toHaveValue(/^[0-9a-f-]{72}$/);
      expect(errors).toEqual([]);
    });
  });
}
