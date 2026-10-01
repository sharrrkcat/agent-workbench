import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test.describe(`${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page, request }) => {
        await request.post('/__test__/session', { data: {} });
        await page.addInitScript((language) => localStorage.setItem('cogita.locale', language), locale);
        await page.goto('/');
      });

      test('reply metrics persist, open a modal accessibly and preserve scrolling', async ({ page, request }, info) => {
        const input = page.locator('.composer textarea');
        await input.fill('two-rounds');
        await input.press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.reply-answer')).toContainText('Working on the conversion.');
        await expect(reply.locator('.reply-metrics')).toHaveCount(0);
        await expect(reply.locator('.reply-metrics')).toBeAttached({ timeout: 20000 });
        if (width !== 390) await reply.hover();
        await expect(reply.locator('.reply-metrics-summary')).toContainText('60');
        await expect(reply.locator('.reply-metrics-summary')).toContainText('30');
        const summaryItems = reply.locator('.reply-metrics-summary > div');
        const labels = locale === 'en'
          ? ['Input tokens', 'Output tokens', 'First response', 'Generation']
          : ['输入 tokens', '输出 tokens', '首响应', '生成'];
        for (const [index, label] of labels.entries()) {
          await summaryItems.nth(index).focus();
          await expect(page.locator('[data-slot=tooltip-content][data-open]')).toHaveText(label);
        }
        if (width !== 390) {
          await input.focus();
          await summaryItems.first().hover();
          await expect(page.locator('[data-slot=tooltip-content][data-open]')).toHaveText(labels[0]);
        }
        await page.keyboard.press('Escape');
        await page.screenshot({ path: info.outputPath('usage-summary.png') });
        const toggle = reply.getByRole('button', { name: locale === 'en' ? 'Usage details' : '用量详情', exact: true });
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await toggle.scrollIntoViewIfNeeded();
        const before = (await toggle.boundingBox())!;
        await toggle.focus();
        await page.keyboard.press('Enter');
        await expect(page.getByRole('dialog')).toBeVisible();
        const overview = page.locator('.reply-metrics-details > dl');
        await expect(overview.locator('dt')).toHaveText(locale === 'en'
          ? ['Input', 'Output', 'First response', 'Total time', 'Generation', 'Model calls']
          : ['输入', '输出', '首响应', '总用时', '生成', '模型调用次数']);
        await expect(overview.locator('dd').last()).toHaveText('3');
        await expect(page.getByRole('dialog').locator('[data-slot=dialog-description]')).toHaveCount(0);
        await expect(page.locator('.reply-metrics-details li [data-slot=separator]')).toHaveCount(3);
        await expect(page.locator('.reply-metrics-details li')).toHaveCount(3);
        await expect(page.locator('.reply-metrics-details')).toContainText('chat-model');
        await expect.poll(async () => Math.abs((await toggle.boundingBox())!.y - before.y)).toBeLessThan(3);
        await expect(page.locator('.reply-metrics-details')).toContainText(locale === 'en' ? 'Cached input tokens' : '缓存输入 tokens');
        const overflow = await page.evaluate(() => [...document.querySelectorAll('body, .workspace, .reply-metrics, .reply-metrics-values')]
          .some((node) => node.scrollWidth > node.clientWidth + 1));
        expect(overflow).toBe(false);
        if (width === 390) expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await page.screenshot({ path: info.outputPath('usage-details.png') });
        await page.keyboard.press('Escape');
        await expect(page.getByRole('dialog')).toHaveCount(0);
        await expect(toggle).toBeFocused();
        await toggle.click();
        await page.getByRole('dialog').getByRole('button', { name: locale === 'en' ? 'Close' : '关闭', exact: true }).click();
        await expect(page.getByRole('dialog')).toHaveCount(0);
        await expect(toggle).toBeFocused();
        const runId = await reply.getAttribute('data-run-id');
        const persisted = await (await request.get(`/api/runs/${runId}`)).json();
        expect(persisted.steps.filter((step: { kind: string }) => step.kind === 'model')).toHaveLength(3);
        await page.reload();
        await expect(page.locator('.reply-metrics-summary')).toContainText('60');
        await expect(page.getByRole('button', { name: locale === 'en' ? 'Usage details' : '用量详情', exact: true })).toHaveAttribute('aria-expanded', 'false');
        await request.post('/__test__/session', { data: {} });
        await page.reload();
        await expect(page.locator('.reply-metrics')).toHaveCount(0);
      });

      test('assistant buttons stay visible while usage and user actions reveal without layout shifts', async ({ page }) => {
        let healthRequests = 0;
        page.on('request', request => { if (request.url().endsWith('/api/health/details')) healthRequests++; });
        await page.reload();
        const input = page.locator('.composer textarea');
        await input.fill('hello');
        await input.press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.reply-metrics')).toBeAttached({ timeout: 20000 });
        const user = page.locator('article.user').last();
        await expect(user.locator('.message-meta time + strong')).toHaveCount(1);
        await expect(reply.locator('.message-meta > :last-child')).toHaveJSProperty('tagName', 'TIME');
        await page.mouse.move(0, 0);
        const actions = reply.locator('.message-actions');
        const usage = reply.locator('.reply-metrics');
        await expect(actions).toHaveCSS('opacity', '1');
        await expect(actions).toHaveCSS('pointer-events', 'auto');
        await expect(usage).toHaveCSS('opacity', width === 390 ? '1' : '0');
        await expect(reply.locator('time')).toHaveCSS('opacity', width === 390 ? '1' : '0');
        const before = await actions.boundingBox();
        if (width !== 390) {
          await reply.hover();
          await expect(usage).toHaveCSS('transition-duration', '0.18s');
          await expect(reply.locator('time')).toHaveCSS('transition-duration', '0.18s');
        }
        await expect(actions).toHaveCSS('opacity', '1');
        await expect(usage).toHaveCSS('opacity', '1');
        await expect(reply.locator('time')).toHaveCSS('opacity', '1');
        expect(await actions.boundingBox()).toEqual(before);
        const names = await actions.locator('button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label')));
        expect(names).toEqual(locale === 'en' ? ['Copy answer', 'Retry reply', 'Usage details', 'Delete reply'] : ['复制回复', '重试回复', '用量详情', '删除回复']);
        await page.mouse.move(0, 0);
        if (width !== 390) {
          await expect(usage).toHaveCSS('transition-duration', '0.18s');
          await expect(reply.locator('time')).toHaveCSS('transition-duration', '0.18s');
          await expect(usage).toHaveCSS('opacity', '0');
          await expect(actions).toHaveCSS('opacity', '1');
          await page.emulateMedia({ reducedMotion: 'reduce' });
          await expect(usage).toHaveCSS('transition-duration', '0s');
          await expect(reply.locator('time')).toHaveCSS('transition-duration', '0s');
          await page.emulateMedia({ reducedMotion: 'no-preference' });
        }
        await actions.locator('button').first().focus();
        await expect(actions).toHaveCSS('opacity', '1');
        await expect(usage).toHaveCSS('opacity', '1');
        await input.focus();
        await page.mouse.move(0, 0);
        await expect(user.locator('.message-actions')).toHaveCSS('opacity', width === 390 ? '1' : '0');
        await expect(user.locator('time')).toHaveCSS('opacity', width === 390 ? '1' : '0');
        if (width !== 390) {
          await user.hover();
          await expect(user.locator('.message-actions')).toHaveCSS('transition-duration', '0.18s');
          await expect(user.locator('time')).toHaveCSS('transition-duration', '0.18s');
        }
        await user.locator('.message-actions button').first().click();
        await input.focus();
        await page.mouse.move(0, 0);
        await expect(user.locator('.message-actions')).toHaveCSS('opacity', '1');
        await user.getByRole('button', { name: locale === 'en' ? 'Cancel' : '取消', exact: true }).click();
        await expect(user.locator('textarea')).toHaveCount(0);
        await expect(page.locator('.status-bar')).toHaveCount(0);
        await expect(page.locator('.composer-hint')).toHaveCount(0);
        expect(healthRequests).toBe(0);
      });

      test('approval shows completed calls and cancellation keeps unknown usage', async ({ page }) => {
        const input = page.locator('.composer textarea');
        await input.fill('approval');
        await input.press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.reply-metrics-controls')).toContainText(locale === 'en' ? 'So far' : '截至当前');
        await expect(reply.locator('.reply-metrics-summary')).toContainText('20');
        await reply.getByRole('button', { name: locale === 'en' ? 'Approve' : '批准', exact: true }).click();
        await expect(reply.locator('.reply-answer')).toContainText('Browser final answer.');
        await expect(reply.locator('.reply-metrics-summary')).toContainText('40');
        await expect(reply.locator('.reply-metrics-controls')).not.toContainText(locale === 'en' ? 'So far' : '截至当前');
        await input.fill('cancel-stream');
        await input.press('Enter');
        const partial = page.locator('article[data-run-id]').last();
        await expect(partial.locator('.reply-answer')).toContainText('Incomplete streamed answer.');
        await partial.getByRole('button', { name: locale === 'en' ? 'Cancel' : '取消', exact: true }).click();
        await expect(partial.locator('.reply-metrics-controls')).toContainText(locale === 'en' ? 'Incomplete statistics' : '统计不完整');
        await expect(partial.locator('.reply-metrics-summary')).toContainText('—');
      });
    });
  }
}
