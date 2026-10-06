import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';

const words = (locale: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ favorite delivery ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('original animation, preview, resource deletion and delivery deletion', async ({ page, request }, info) => {
      const labels = words(locale);
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const main = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'Favorite image replies',
        model_profile_id: main.id, bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001',
        keywords: ['bot'], reply_message_limit: 1, context_policy: {} } }));
      let assetId: number | undefined;
      try {
        const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { target_kind: 'group', target_id: '7788' } }));
        const sid = session.session_id;
        const fixture = await json(request.post(`/__test__/qq/${sid}/resources?count=1`));
        assetId = fixture.resources[0].asset_id;
        await json(request.patch(`/api/qq/resources/${assetId}`, { data: { is_favorite: true, description: 'Celebration animation' } }));
        await page.goto(`/projects/${project.id}?session=${sid}`);
        await json(request.post(`/__test__/qq/${sid}/reply/resource-image`));
        const bubble = page.locator('[data-qq-delivery]').first();
        await expect(bubble.locator('img')).toHaveAttribute('src', /\.gif$/);
        await expect(bubble.locator('img')).toHaveAttribute('alt', 'Celebration animation');
        await expect.poll(() => bubble.locator('img').evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true);
        await bubble.locator('.qq-image-button').click();
        const preview = page.getByRole('dialog', { name: 'Celebration animation', exact: true });
        await expect(preview).toBeVisible();
        await expect(preview.locator('img')).toHaveAttribute('src', /\.gif$/);
        await page.screenshot({ path: info.outputPath('favorite-animation-preview.png') });
        await page.keyboard.press('Escape');
        await expect(preview).toBeHidden();
        await expect(bubble.locator('.qq-image-button')).toBeFocused();
        const delivery = (await json(request.get(`/api/qq/sessions/${sid}/deliveries`))).items[0];
        expect(delivery.kind).toBe('resource_image');
        expect(delivery.asset_id).toBe(assetId);
        expect(delivery.prompt).toBeNull();
        await json(request.delete(`/api/qq/resources/${assetId}`));
        await expect(bubble.locator('[data-qq-media-state="deleted"]')).toHaveText(labels.qq.resources.imagePlaceholder);
        await expect(bubble.locator('img')).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('favorite-deleted-placeholder.png') });
        await json(request.delete(`/api/qq/sessions/${sid}/deliveries/${delivery.id}`));
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        expect(errors).toEqual([]);
      } finally {
        if (assetId !== undefined) await request.delete(`/api/qq/resources/${assetId}`);
        await request.delete(`/api/projects/${project.id}`);
      }
    });
  });
}
