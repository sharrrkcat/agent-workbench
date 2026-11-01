import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse } from '@playwright/test';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`Harness and QQ compaction ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });

    test('shows loop summaries in sequence and inspects them after reload', async ({ page, request }, info) => {
      const labels = words(locale, 'personas'), runs = words(locale, 'runs');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await json(request.post('/__test__/session', { data: { loop_compaction: true, show_full_processing: true } }));
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      await page.goto('/');
      await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
      const settings = page.getByRole('dialog', { name: labels.sessionSettings });
      await expect(settings.getByRole('switch', { name: labels.historyEnabled, exact: true })).not.toBeChecked();
      await expect(settings.getByRole('switch', { name: labels.autoCompaction, exact: true })).toBeEnabled();
      await expect(settings.getByRole('button', { name: labels.tokenBudget, exact: true })).toBeEnabled();
      await page.keyboard.press('Escape');
      const input = page.locator('.composer textarea');
      await input.fill(`loop-compaction-fixture ${Date.now()}`);
      await input.press('Enter');
      await expect(page.getByText(runs.compaction.running, { exact: true }).first()).toBeVisible();
      const reply = page.locator('article[data-run-id]').last();
      await expect(reply.locator('.reply-answer')).toContainText('Browser final answer.');
      const runId = await reply.getAttribute('data-run-id');
      const run = await json(request.get(`/api/runs/${runId}`));
      expect(run.steps.filter((step: { kind: string }) => step.kind === 'compaction')).toHaveLength(3);
      await reply.locator('.processing-toggle').click();
      await expect(reply.locator('[data-compaction-step]')).toHaveCount(3);
      const text = await reply.locator('.processing-list').innerText();
      expect(text.indexOf('test_echo')).toBeLessThan(text.indexOf(runs.compaction.completed));
      await reply.getByRole('button', { name: runs.context.details, exact: true }).click();
      const detail = page.getByRole('dialog', { name: runs.context.details });
      const source = detail.locator('[data-context-source=summary]');
      await expect(source).toContainText(runs.compaction.runSummary);
      await source.click();
      await expect(detail.locator('.context-text')).toContainText('42 EUR');
      await expect(detail.locator('.context-text')).toContainText('Do not send email');
      await detail.getByRole('button', { name: runs.context.sourceInfo, exact: true }).click();
      await expect(page.locator('.context-info')).toContainText(runs.compaction.throughRound);
      await page.keyboard.press('Escape');
      await page.screenshot({ path: info.outputPath('loop-summary.png') });
      await page.reload();
      await page.locator('article[data-run-id]').last().getByRole('button', { name: runs.context.details, exact: true }).click();
      await expect(page.locator('[data-context-source=summary]')).toContainText(runs.compaction.runSummary);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });

    test('QQ uses historical summaries and retains delivery-only presentation', async ({ page, request }, info) => {
      const runs = words(locale, 'runs');
      await json(request.post('/__test__/session'));
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const main = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const stamp = Date.now();
      const model = await json(request.post('/api/models/profiles', { data: { name: 'QQ summary model', alias: `qq-summary-${stamp}`,
        kind: 'llm', model_ref: 'fake', source: main.source, context_window_tokens: 8192, request_options: { streaming: true } } }));
      const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'QQ memory', bot_account: String(stamp),
        model_profile_id: model.id, websocket_url: 'ws://127.0.0.1:3001', keywords: ['bot'], reply_message_limit: 1,
        context_policy: { compaction: { trigger_percent: 25, target_percent: 15, max_summary_tokens: 512 } } } }));
      try {
        const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { target_kind: 'group', target_id: '7788' } }));
        await page.goto(`/projects/${project.id}?session=${session.session_id}`);
        await json(request.post(`/__test__/qq/${session.session_id}/reply/compaction`));
        const fixture = await json(request.post(`/__test__/qq/${session.session_id}/reply/compaction`));
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(2);
        const reply = page.locator(`article[data-run-id="${fixture.run_id}"]`);
        await expect(reply.locator('.status-done')).toBeVisible();
        await reply.locator('.processing-toggle').click();
        await expect(reply.locator('[data-compaction-step]')).toHaveCount(1);
        await reply.getByRole('button', { name: runs.context.details, exact: true }).click();
        const detail = page.getByRole('dialog', { name: runs.context.details });
        await detail.locator('[data-context-source=summary]').click();
        await expect(detail.locator('.context-text')).toContainText('42 EUR');
        await detail.getByRole('button', { name: runs.context.sourceInfo, exact: true }).click();
        await expect(page.locator('.context-info')).toContainText(runs.compaction.batchBoundary);
        await page.keyboard.press('Escape');
        await page.screenshot({ path: info.outputPath('qq-summary.png') });
        await page.reload();
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(2);
        expect((await json(request.get(`/api/qq/sessions/${session.session_id}`))).paused).toBe(false);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      } finally {
        await request.delete(`/api/projects/${project.id}`);
        await request.delete(`/api/models/profiles/${model.id}`);
      }
    });
  });
}
