import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`on-demand history ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test('configures, resets and privately recovers history without summary calls', async ({ page, request }, info) => {
        const session = await (await request.post('/__test__/session', { data: { history_retrieval: true, show_full_processing: true } })).json();
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/');
        await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
        const settings = page.getByRole('dialog', { name: labels.sessionSettings });
        await expect(settings.getByRole('button', { name: labels.historyRetrieval, exact: true })).toHaveAttribute('aria-pressed', 'true');
        await expect(settings.getByRole('switch', { name: labels.autoCompaction, exact: true })).toHaveCount(0);
        await settings.getByRole('button', { name: labels.compactionAdvanced, exact: true }).click();
        await expect(settings.getByRole('spinbutton', { name: labels.checkpointTokens, exact: true })).toHaveValue('512');
        await expect(settings.getByRole('spinbutton', { name: labels.retrievalTrigger, exact: true })).toHaveValue('40');
        await page.screenshot({ path: info.outputPath('retrieval-settings.png'), animations: 'disabled' });
        await page.keyboard.press('Escape');
        const input = page.locator('.composer textarea');
        await input.fill('history-retrieval-fixture: remember budget 47 EUR.');
        await input.press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.reply-answer')).toContainText('Recovered budget: 47 EUR.');
        const runId = await reply.getAttribute('data-run-id');
        const run = await (await request.get(`/api/runs/${runId}`)).json();
        const resets = run.steps.filter((step: { metadata?: { operation?: string } }) => step.metadata?.operation === 'reset');
        expect(resets.length).toBeGreaterThanOrEqual(3);
        expect(run.steps.some((step: { kind: string }) => step.kind === 'compaction')).toBe(false);
        expect(resets.every((step: { metadata: { llm?: unknown } }) => !step.metadata.llm)).toBe(true);
        const title = locale === 'en' ? 'Context detail' : '上下文详情';
        await reply.getByRole('button', { name: title, exact: true }).click();
        const detail = page.getByRole('dialog', { name: title });
        await detail.locator('[data-context-source=context_memory]').click();
        await expect(detail.locator('.context-text')).toContainText('Budget: 47 EUR.');
        await expect(detail.locator('.context-footer')).toContainText(labels.historyRetrieval);
        await page.screenshot({ path: info.outputPath('retrieval-detail.png'), animations: 'disabled' });
        await page.keyboard.press('Escape');
        await input.fill('/compact');
        await input.press('Enter');
        await expect(page.locator('[data-compaction-run]').last()).toBeVisible();
        await page.reload();
        await expect(page.locator('article[data-run-id]').last().locator('.reply-answer')).toContainText('Recovered budget: 47 EUR.');
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        const saved = await (await request.get(`/api/sessions/${session.session_id}`)).json();
        expect(saved.effective.context_policy.strategy).toBe('history_retrieval');
      });
    });
  }
}
