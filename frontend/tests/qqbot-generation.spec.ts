import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';
import { chooseOption } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const result = await response; expect(result.ok(), await result.text()).toBe(true); return result.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ generation ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('settings, generated image, preview, deletion and generation failure', async ({ page, request }, info) => {
      const labels = words(locale, 'personas'), models = words(locale, 'llm');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const main = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const stamp = Date.now();
      const model = await json(request.post('/api/models/profiles', { data: { name: 'QQ image generator', alias: `qq-draw-${stamp}`,
        kind: 'image_generation', model_ref: 'draw', source: main.source, parameters: { n: 3 } } }));
      const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'QQ generation',
        model_profile_id: main.id, bot_account: String(stamp), websocket_url: 'ws://127.0.0.1:3001',
        keywords: ['bot'], reply_message_limit: 1, context_policy: {} } }));
      try {
        const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { target_kind: 'group', target_id: '7788' } }));
        const sid = session.session_id;
        await page.goto(`/projects/${project.id}`);
        await page.getByRole('tab', { name: labels.qq.tabs.images, exact: true }).click();
        const selector = page.getByLabel(labels.qq.imageGenerationModel, { exact: true });
        await expect(selector).toContainText(labels.qq.noImageGeneration);
        await selector.click();
        await expect(page.getByRole('option', { name: main.name, exact: true })).toHaveCount(0);
        await page.getByRole('option', { name: model.name, exact: true }).click();
        const size = page.getByLabel(models.imageGeneration.size, { exact: true });
        await size.fill('512x512');
        await chooseOption(page.getByLabel(models.imageGeneration.quality, { exact: true }), models.imageGeneration.values.high);
        await chooseOption(page.getByLabel(models.imageGeneration.style, { exact: true }), models.imageGeneration.values.vivid);
        await page.route(`**/api/projects/${project.id}`, async (route) => {
          if (route.request().method() === 'PATCH') await route.fulfill({ status: 500, json: { error: { code: 'TEST_FAILURE', message: 'Fixture save failure' } } });
          else await route.continue();
        });
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByText('Fixture save failure', { exact: false })).toBeVisible();
        await expect(size).toHaveValue('512x512');
        await page.unroute(`**/api/projects/${project.id}`);
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        await page.reload();
        await page.getByRole('tab', { name: labels.qq.tabs.images, exact: true }).click();
        await expect(selector).toContainText(model.name);
        await expect(size).toHaveValue('512x512');
        expect((await json(request.get(`/api/projects/${project.id}`))).image_generation_options).toEqual({ size: '512x512', quality: 'high', style: 'vivid' });
        await page.goto(`/projects/${project.id}?session=${sid}`);
        await json(request.post(`/__test__/qq/${sid}/reply/image-generated`));
        const bubble = page.locator('[data-qq-delivery]').first();
        await expect(bubble.locator('img')).toHaveAttribute('alt', 'Browser generated image');
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(1);
        await bubble.locator('.qq-image-button').click();
        const preview = page.getByRole('dialog', { name: 'Browser generated image', exact: true });
        await expect(preview).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(preview).toBeHidden();
        await expect(bubble.locator('.qq-image-button')).toBeFocused();
        await page.screenshot({ path: info.outputPath('qq-generated-image.png') });
        const delivery = (await json(request.get(`/api/qq/sessions/${sid}/deliveries`))).items[0];
        expect(delivery.kind).toBe('generated_image');
        await json(request.delete(`/api/qq/sessions/${sid}/deliveries/${delivery.id}`));
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(0);
        await json(request.post(`/__test__/qq/${sid}/reply/image-failure`));
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(1);
        await expect(page.locator('[data-qq-delivery]')).toContainText('Image generation failed; here is a text reply.');
        expect((await json(request.get(`/api/qq/sessions/${sid}`))).paused).toBe(false);
        const held = json(request.post(`/__test__/qq/${sid}/reply/image-hold`));
        await expect.poll(async () => (await json(request.get(`/api/qq/sessions/${sid}`))).busy).toBe(true);
        await expect(page.getByRole('button', { name: labels.qq.stop, exact: true })).toBeEnabled();
        await page.getByRole('button', { name: labels.qq.stop, exact: true }).click();
        await held;
        await expect.poll(async () => (await json(request.get(`/api/qq/sessions/${sid}`))).busy).toBe(false);
        expect((await json(request.get(`/api/qq/sessions/${sid}/deliveries`))).items).toHaveLength(1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.goto(`/projects/${project.id}`);
        await page.getByRole('tab', { name: labels.qq.tabs.images, exact: true }).click();
        await chooseOption(selector, labels.qq.noImageGeneration);
        await expect(size).toHaveCount(0);
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        const saved = await json(request.get(`/api/projects/${project.id}`));
        expect(saved.image_generation_model_profile_id).toBeNull();
        expect(saved.image_generation_options.size).toBe('512x512');
        expect(errors).toEqual([]);
      } finally {
        await request.delete(`/api/projects/${project.id}`);
        await request.delete(`/api/models/profiles/${model.id}`);
      }
    });
  });
}
