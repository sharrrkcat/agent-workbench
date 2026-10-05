import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';

const words = (locale: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ icebreaker ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('defaults, failed save, persistence and disabling retain timing values', async ({ page, request }, info) => {
      const labels = words(locale);
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'Quiet group',
        bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001', context_policy: {} } }));
      const url = `/api/projects/${project.id}`;
      try {
        await page.goto(`/projects/${project.id}`);
        const enabled = page.getByRole('switch', { name: labels.qq.icebreakerEnabled, exact: true });
        const cold = page.getByLabel(labels.qq.icebreakerCold, { exact: true });
        const wait = page.getByLabel(labels.qq.icebreakerWait, { exact: true });
        const cooldown = page.getByLabel(labels.qq.icebreakerCooldown, { exact: true });
        const save = page.getByRole('button', { name: labels.save, exact: true });
        await expect(enabled).not.toBeChecked();
        await expect(cold).toHaveCount(0);
        await enabled.click();
        await expect(cold).toHaveValue('7200');
        await expect(wait).toHaveValue('120');
        await expect(cooldown).toHaveValue('10800');
        await cold.fill('60');
        await wait.fill('7');
        await cooldown.fill('600');
        await page.route(`**${url}`, async (route) => {
          if (route.request().method() === 'PATCH') await route.fulfill({ status: 500,
            json: { error: { code: 'TEST_FAILURE', message: 'Fixture icebreaker save failure' } } });
          else await route.continue();
        });
        await save.click();
        await expect(page.getByText('Fixture icebreaker save failure', { exact: false })).toBeVisible();
        await expect(enabled).toBeChecked();
        await expect(cold).toHaveValue('60');
        await expect(wait).toHaveValue('7');
        await expect(cooldown).toHaveValue('600');
        expect((await json(request.get(url))).icebreaker_enabled).toBe(false);
        await page.unroute(`**${url}`);
        await save.click();
        await expect(save).toBeDisabled();
        await page.reload();
        await expect(enabled).toBeChecked();
        await expect(cold).toHaveValue('60');
        await expect(wait).toHaveValue('7');
        await expect(cooldown).toHaveValue('600');
        await enabled.click();
        await expect(cold).toHaveCount(0);
        await save.click();
        await expect(save).toBeDisabled();
        await page.reload();
        await expect(enabled).not.toBeChecked();
        const saved = await json(request.get(url));
        expect(saved.icebreaker_enabled).toBe(false);
        expect([saved.icebreaker_cold_seconds, saved.icebreaker_wait_seconds, saved.icebreaker_cooldown_seconds]).toEqual([60, 7, 600]);
        await enabled.click();
        await expect(cold).toHaveValue('60');
        await expect(wait).toHaveValue('7');
        await expect(cooldown).toHaveValue('600');
        await cold.scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('qq-icebreaker-settings.png') });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await save.click();
        await expect(save).toBeDisabled();
        expect(errors).toEqual([]);
      } finally {
        await request.delete(url);
      }
    });
  });
}
