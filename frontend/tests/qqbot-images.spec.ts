import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';
import { chooseOption } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ images ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('ordered media, separate bubbles, preview, old pending refresh and settings', async ({ page, request }, info) => {
      const labels = words(locale, 'personas'), chat = words(locale, 'chat');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'QQ images',
        bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001', keywords: ['bot'], context_policy: {} } }));
      try {
        expect(project.image_input_enabled).toBe(false);
        const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { title: 'QQ images', target_kind: 'group', target_id: '7788' } }));
        const sid = session.session_id;
        const fixture = await json(request.post(`/__test__/qq/${sid}/media`));
        await page.goto(`/projects/${project.id}?session=${sid}`);
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(50);
        const row = (number: number) => page.locator(`[data-qq-incoming="${fixture.ids[number]}"]`);
        const mixed = row(57), pure = row(58), face = row(59), failed = row(60);
        await expect(mixed.locator('.qq-message-content > span')).toHaveText(['Before ', ' between ', ' after']);
        await expect(mixed.locator('.qq-message-content > .qq-image-button')).toHaveCount(2);
        expect(await mixed.locator('.qq-message-content').evaluate((node) => Array.from(node.children)
          .filter((child) => child.tagName === 'SPAN' || child.tagName === 'BUTTON').map((child) => child.tagName))).toEqual(['SPAN', 'BUTTON', 'SPAN', 'BUTTON', 'SPAN']);
        await expect(mixed.locator('[data-slot="bubble"]')).toHaveCount(1);
        await expect(pure.locator('[data-slot="bubble"]')).toHaveCount(1);
        await expect(pure.locator('.qq-message-content > span')).toHaveCount(0);
        await expect(pure.locator('img')).toHaveAttribute('src', /\.gif$/);
        await expect(failed.locator('[data-qq-media-state="failed"]')).toHaveText(labels.qq.mediaFailed.replace('{{name}}', labels.image));
        await expect(face.locator('[data-qq-media-kind="face"] img')).toHaveCSS('width', '24px');
        for (const [number, kind, maximum] of [[57, 'image', 240], [58, 'sticker', 160]] as const) {
          const image = row(number).locator(`[data-qq-media-kind="${kind}"] img`);
          await image.scrollIntoViewIfNeeded();
          await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true);
          const size = (await image.boundingBox())!;
          expect(size.width).toBeLessThanOrEqual(maximum);
          expect(size.height).toBeLessThanOrEqual(maximum);
          expect(size.width / size.height).toBeCloseTo(640 / 480, 1);
        }
        await pure.locator('.qq-image-button').click();
        const preview = page.getByRole('dialog', { name: labels.qq.sticker, exact: true });
        await expect(preview).toBeVisible();
        await expect(preview.locator('img')).toHaveAttribute('src', /\.gif$/);
        await page.keyboard.press('Escape');
        await expect(preview).toBeHidden();
        await expect(pure.locator('.qq-image-button')).toBeFocused();
        await page.screenshot({ path: info.outputPath('qq-images.png') });
        await page.getByRole('button', { name: chat.loadEarlier, exact: true }).click();
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(60);
        const old = row(1);
        await expect(old.locator('[data-qq-media-state="pending"]')).toBeAttached();
        await request.post(`/__test__/qq/${sid}/media/complete`);
        await expect(old.locator('.qq-image-button')).toHaveCount(1);
        await expect(old.getByRole('button', { name: labels.qq.status.skipped, exact: true })).toBeAttached();
        for (const description of ['共享图片描述', '更新后的图片描述']) {
          await json(request.post(`/__test__/qq/${sid}/media/description`, { data: { description } }));
          await expect(old.locator('img')).toHaveAttribute('alt', description);
          await expect(mixed.locator('img').first()).toHaveAttribute('alt', description);
          await expect(pure.locator('img')).toHaveAttribute('alt', description);
        }
        await pure.locator('.qq-image-button').click();
        const describedPreview = page.getByRole('dialog', { name: '更新后的图片描述', exact: true });
        await expect(describedPreview.locator('img')).toHaveAttribute('alt', '更新后的图片描述');
        await page.keyboard.press('Escape');
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.goto(`/projects/${project.id}`);
        const toggle = page.getByRole('switch', { name: labels.qq.imageInputEnabled, exact: true });
        await expect(toggle).not.toBeChecked();
        await expect(page.getByText(labels.qq.imageInputHint, { exact: true })).toBeVisible();
        await toggle.click();
        const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
        const descriptionModel = page.getByLabel(labels.qq.imageDescriptionModel, { exact: true });
        await expect(descriptionModel).toContainText(labels.qq.noDescriptionModel);
        await chooseOption(descriptionModel, model.name);
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        expect((await json(request.get(`/api/projects/${project.id}`))).image_input_enabled).toBe(true);
        await page.reload();
        await expect(toggle).toBeChecked();
        await expect(descriptionModel).toContainText(model.name);
        expect((await json(request.get(`/api/projects/${project.id}`))).image_description_model_profile_id).toBe(model.id);
        await chooseOption(descriptionModel, labels.qq.noDescriptionModel);
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        expect((await json(request.get(`/api/projects/${project.id}`))).image_description_model_profile_id).toBeNull();
        expect(errors).toEqual([]);
      } finally {
        await request.delete(`/api/projects/${project.id}`);
      }
    });
  });
}
