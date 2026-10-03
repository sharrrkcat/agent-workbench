import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test.describe(`context meter ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test('actual usage, hover/focus/touch, streaming, refresh and pruning', async ({ page, request }, info) => {
        const zh = locale === 'zh-CN';
        const session = await (await request.post('/__test__/session', { data: {} })).json();
        await page.addInitScript((language) => localStorage.setItem('cogita.locale', language), locale);
        await page.goto('/');
        const meter = page.locator('.context-meter');
        const card = page.locator('.context-meter-card');
        await expect(meter).toHaveAttribute('aria-label', new RegExp(zh ? '尚无匹配配置的调用' : 'No calls'));
        const ring = (await meter.boundingBox())!;
        const model = (await page.locator('.chat-model-select').boundingBox())!;
        expect(ring.x + ring.width).toBeLessThanOrEqual(model.x);
        if (width === 390) {
          expect(ring.width).toBeGreaterThanOrEqual(44);
          expect(ring.height).toBeGreaterThanOrEqual(44);
          await meter.tap();
        } else await meter.hover();
        await expect(card).toBeVisible();
        await page.keyboard.press('Escape');
        await meter.focus();
        await expect(card).toBeVisible();
        await page.keyboard.press('Escape');
        const input = page.locator('.composer textarea');
        await input.fill('context-usage');
        await input.press('Enter');
        await expect(meter).toHaveAttribute('aria-label', /24.8% · 8,136 \/ 32,768 tokens/);
        await meter.click();
        await expect(card).toContainText('4,096');
        await expect(card).toContainText('25,395');
        await expect(card).not.toContainText(zh ? '最近一次模型调用' : 'Latest model call');
        for (const label of zh ? ['模型', '上下文窗口', '已用输入'] : ['Model', 'Context window', 'Input used']) {
          await expect(card.locator('dt').filter({ hasText: new RegExp(`^${label}$`) })).toHaveCount(0);
        }
        await expect(card).not.toContainText(zh ? '正在生成' : 'Generating');
        await expect(meter.locator('svg')).toHaveAttribute('data-full', 'false');
        await expect(meter.locator('.context-meter-fill')).toHaveAttribute('stroke-dasharray', `${8136 / 32768 * 100} 100`);
        await page.screenshot({ path: info.outputPath('context-meter.png') });
        await page.keyboard.press('Escape');
        await page.reload();
        await expect(meter).toHaveAttribute('aria-label', /8,136 \/ 32,768/);
        await input.fill('context-no-usage');
        await input.press('Enter');
        await meter.click();
        await expect(card).toContainText(zh ? '正在生成' : 'Generating');
        await expect(meter).toHaveAttribute('aria-label', /8,136 \/ 32,768/);
        await expect(meter).toHaveAttribute('aria-label', new RegExp(zh ? '未提供用量' : 'Usage not provided'));
        await page.keyboard.press('Escape');
        await page.reload();
        await expect(meter).toHaveAttribute('aria-label', new RegExp(zh ? '未提供用量' : 'Usage not provided'));
        const replies = page.locator('article[data-run-id]');
        const id = await replies.last().getAttribute('data-run-id');
        expect((await request.delete(`/api/runs/${id}`)).ok()).toBeTruthy();
        await expect(meter).toHaveAttribute('aria-label', /8,136 \/ 32,768/);
        expect((await request.patch(`/api/models/profiles/${session.model_profile_id}`, { data: { context_window_tokens: 16384 } })).ok()).toBeTruthy();
        await page.reload();
        await expect(meter).toHaveAttribute('aria-label', new RegExp(zh ? '尚无匹配配置的调用' : 'No calls'));
        await request.patch(`/api/models/profiles/${session.model_profile_id}`, { data: { context_window_tokens: 32768 } });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      });
    });
  }
}
