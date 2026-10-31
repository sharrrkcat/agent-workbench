import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';

const words = (locale: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const result = await response; expect(result.ok(), await result.text()).toBe(true); return result.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ commands ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('administrator settings and program transcript survive refresh without model runs', async ({ page, request }, info) => {
      const labels = words(locale), errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'QQ commands', context_policy: {},
        bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001', model_profile_id: model.id } }));
      try {
        await page.goto(`/projects/${project.id}`);
        const admin = page.getByLabel(labels.qq.adminQQ, { exact: true });
        const save = page.getByRole('button', { name: labels.save, exact: true });
        await expect(admin).toHaveValue('');
        await admin.fill(project.bot_account);
        await save.click();
        await expect(admin).toHaveJSProperty('validationMessage', labels.qq.adminIsBot);
        await admin.fill('invalid');
        await save.click();
        expect(await admin.evaluate((node: HTMLInputElement) => node.validity.valid)).toBe(false);
        await admin.fill('9999');
        await page.route(`**/api/projects/${project.id}`, (route) => route.request().method() === 'PATCH'
          ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'SAVE_FAILED', message: 'Administrator save failed' } }) })
          : route.continue());
        await save.click();
        await expect(page.getByText('Administrator save failed', { exact: false })).toBeVisible();
        await expect(admin).toHaveValue('9999');
        await page.unroute(`**/api/projects/${project.id}`);
        await save.click();
        await expect(save).toBeDisabled();
        expect((await json(request.get(`/api/projects/${project.id}`))).admin_qq).toBe('9999');
        await admin.fill(''); await save.click(); await expect(save).toBeDisabled();
        expect((await json(request.get(`/api/projects/${project.id}`))).admin_qq).toBeNull();
        await admin.fill('9999'); await save.click(); await expect(save).toBeDisabled();
        const session = await json(request.post(`/api/projects/${project.id}/sessions`, {
          data: { title: 'Administrator', target_kind: 'friend', target_id: '9999' } }));
        await page.goto(`/projects/${project.id}?session=${session.session_id}`);
        await json(request.post(`/__test__/qq/${session.session_id}/command`, { data: { text: '/cogita pause' } }));
        await expect(page.locator('[data-qq-program="command"]')).toHaveCount(1);
        await expect(page.locator('[data-qq-incoming]')).toContainText('/cogita pause');
        await expect(page.locator('[data-qq-incoming]').getByRole('button', { name: labels.qq.status.command_done, exact: true })).toBeVisible();
        await json(request.post(`/__test__/qq/${session.session_id}/command`, { data: { text: '/cogita check' } }));
        await expect(page.locator('[data-qq-program="command"]')).toHaveCount(2);
        await expect(page.locator('[data-qq-program]').filter({ hasText: 'health: ok' })).toBeVisible();
        await json(request.post(`/__test__/qq/${session.session_id}/notification`));
        await expect(page.locator('[data-qq-program="notification"]')).toContainText('QQ_RUN_FAILED');
        await page.reload();
        await expect(page.locator('[data-qq-program]')).toHaveCount(3);
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(2);
        const deliveries = (await json(request.get(`/api/qq/sessions/${session.session_id}/deliveries`))).items;
        expect(deliveries.every((row: { run_id: string | null; status: string }) => row.run_id === null && row.status === 'sent')).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.locator('[data-qq-program="notification"]').scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('qq-program-messages.png') });
        const removed = deliveries.find((row: { origin: string }) => row.origin === 'notification');
        await json(request.delete(`/api/qq/sessions/${session.session_id}/deliveries/${removed.id}`));
        await expect(page.locator('[data-qq-program="notification"]')).toHaveCount(0);
        expect(errors).toEqual([]);
      } finally {
        await request.delete(`/api/projects/${project.id}`);
      }
    });
  });
}
