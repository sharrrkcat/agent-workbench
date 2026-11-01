import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test.describe(`compaction ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test('records compaction separately and inspects the actual summary', async ({ page, request }, info) => {
        const zh = locale === 'zh-CN';
        const session = await (await request.post('/__test__/session', { data: { compaction: true, show_full_processing: true } })).json();
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/');
        const input = page.locator('.composer textarea');
        await input.fill('Remember the budget and the restriction.');
        await input.press('Enter');
        await expect(page.getByText(zh ? '正在压缩上下文' : 'Compacting context', { exact: true }).first()).toBeVisible();
        await page.locator('.context-meter').click();
        await expect(page.locator('.context-meter-card')).toContainText(zh ? '正在压缩' : 'Compacting context');
        await page.keyboard.press('Escape');
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.reply-answer')).toContainText('Browser final answer.');
        const runId = await reply.getAttribute('data-run-id');
        const run = await (await request.get(`/api/runs/${runId}`)).json();
        const compactions = run.steps.filter((step: { kind: string }) => step.kind === 'compaction');
        expect(compactions.length).toBeGreaterThan(0);
        expect(compactions.every((step: { metadata: { llm: { message_id: string | null } } }) => step.metadata.llm.message_id === null)).toBe(true);
        const title = zh ? '上下文详情' : 'Context detail';
        await reply.getByRole('button', { name: title, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: title });
        await dialog.locator('[data-context-source=summary]').click();
        await expect(dialog.locator('.context-text')).toContainText('42 EUR');
        await expect(dialog.locator('.context-text')).toContainText('Do not send email');
        await dialog.getByRole('combobox').click();
        await page.getByRole('option').filter({ hasText: zh ? '压缩' : 'Compaction' }).first().click();
        await expect(dialog.locator('[data-context-source=summary]')).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('compaction.png') });
        await page.keyboard.press('Escape');
        await page.reload();
        await page.locator('article[data-run-id]').last().getByRole('button', { name: title, exact: true }).click();
        await expect(page.locator('[data-context-source=summary]')).toBeVisible();
        expect((await request.get(`/api/sessions/${session.session_id}`)).ok()).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      });
    });
  }
}
