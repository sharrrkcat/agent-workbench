import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  const title = locale === 'en' ? 'Context detail' : '上下文详情';
  for (const width of [1366, 390]) {
    test.describe(`message window ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test('switches strategies, preserves settings and inspects a bounded raw request', async ({ page, request }, info) => {
        const session = await (await request.post('/__test__/session', { data: { compaction: true } })).json();
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/');
        await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
        const settings = page.getByRole('dialog', { name: labels.sessionSettings });
        const token = settings.getByRole('button', { name: labels.tokenBudget, exact: true });
        const message = settings.getByRole('button', { name: labels.messageWindow, exact: true });
        await expect(token).toHaveAttribute('aria-pressed', 'true');
        await message.click();
        await expect(settings.getByRole('switch', { name: labels.autoCompaction, exact: true })).toHaveCount(0);
        const limit = settings.getByRole('spinbutton', { name: labels.maxMessages, exact: true });
        await expect(limit).toHaveValue('100');
        await limit.fill('0');
        await expect(limit).toHaveAttribute('aria-invalid', 'true');
        await settings.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(settings).toBeVisible();
        await limit.fill('3');
        const history = settings.getByRole('switch', { name: labels.historyEnabled, exact: true });
        await history.uncheck();
        await expect(limit).toBeDisabled();
        await expect(token).toBeDisabled();
        await history.check();
        await token.click();
        await settings.getByRole('button', { name: labels.compactionAdvanced, exact: true }).click();
        await expect(settings.getByRole('spinbutton', { name: labels.compactionSummaryTokens, exact: true })).toHaveValue('512');
        await message.click();
        await expect(limit).toHaveValue('3');
        await expect(limit.locator('..')).not.toHaveAttribute('data-invalid');
        await page.screenshot({ path: info.outputPath('message-window-settings.png'), animations: 'disabled' });
        await settings.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(settings).toBeHidden();
        const saved = await (await request.get(`/api/sessions/${session.session_id}`)).json();
        expect(saved.context_policy.strategy).toBe('message_window');
        expect(saved.context_policy.compaction).toEqual(session.context_policy.compaction);
        await page.reload();
        await page.locator('.composer textarea').fill('Use the recent raw history.');
        await page.locator('.composer textarea').press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.reply-answer')).toContainText('Browser final answer.');
        const runId = await reply.getAttribute('data-run-id');
        const run = await (await request.get(`/api/runs/${runId}`)).json();
        expect(run.steps.some((step: { kind: string }) => step.kind === 'compaction')).toBe(false);
        await reply.getByRole('button', { name: title, exact: true }).click();
        const detail = page.getByRole('dialog', { name: title });
        await expect(detail.locator('[data-context-source=summary]')).toHaveCount(0);
        await expect(detail.locator('[data-context-source=history]')).toHaveCount(2);
        await expect(detail.locator('.context-footer')).toContainText(locale === 'en' ? 'History message limit: 3' : '历史消息上限：3');
        await page.screenshot({ path: info.outputPath('message-window-context.png'), animations: 'disabled' });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.keyboard.press('Escape');
        await request.patch(`/api/sessions/${session.session_id}`, { data: { context_policy: { strategy: 'token_budget' } } });
        await page.reload();
        await page.locator('article[data-run-id]').last().getByRole('button', { name: title, exact: true }).click();
        await expect(page.getByRole('dialog', { name: title }).locator('.context-footer')).toContainText(locale === 'en' ? 'History message limit: 3' : '历史消息上限：3');
      });
    });
  }
}
