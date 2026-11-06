import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { readHistory, readMessages } from './history';
import { openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const chat = words(locale, 'chat'), runs = words(locale, 'runs'), personas = words(locale, 'personas');
  test.describe(`Manual compaction ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    });

    test('slash completion, independent checkpoint, queued answer and refresh', async ({ page, request }, info) => {
      const session = await (await request.post('/__test__/session', { data: { compaction: 'hold' } })).json();
      await request.patch(`/api/sessions/${session.session_id}`, { data: {overrides: {context_policy: {
        compaction: { enabled: false, trigger_percent: 50, target_percent: 35, max_summary_tokens: 512 } }}} });
      const before = await readHistory(request, session.session_id);
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message));
      const sent: string[] = []; page.on('request', (r) => {
        if (r.method() === 'POST' && r.url().endsWith('/messages')) sent.push(r.postDataJSON().content);
      });
      await page.goto('/');
      const input = page.locator('.composer textarea');
      const menu = page.getByRole('listbox', { name: chat.compactCommand.menu });
      await input.fill('/');
      await expect(menu.getByRole('option')).toHaveCount(1);
      await expect(menu.getByRole('option')).toBeEnabled();
      await expect(input).toBeFocused();
      await page.screenshot({ path: info.outputPath('compact-command.png') });
      await input.press('Escape'); await expect(menu).toBeHidden();
      await input.fill('/com'); await input.press('Tab');
      await expect(input).toHaveValue('/compact');
      await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true });
      await expect(page.locator('[data-compaction-run]')).toHaveCount(0);
      await input.press('Shift+Enter');
      await expect(page.locator('[data-compaction-run]')).toHaveCount(0);
      await input.fill('/compact extra');
      await expect(page.locator('.composer').getByRole('button', { name: chat.compactCommand.execute, exact: true })).toBeDisabled();
      await expect(page.getByText(chat.compactCommand.arguments, { exact: true })).toBeVisible();
      await input.fill('/comp');
      if (width === 390) await menu.getByRole('option').click();
      else { await input.press('ArrowDown'); await input.press('Enter'); }
      const marker = page.locator('[data-compaction-run]').last();
      await expect(marker).toContainText(runs.compaction.running);
      await expect(input).toHaveValue('');
      await input.fill('After manual compaction'); await input.press('Enter');
      await expect(page.getByRole('region', { name: chat.queue.label })).toContainText('After manual compaction');
      expect(sent).toEqual([]);
      await request.post('/__test__/release-compaction');
      await expect(marker).toContainText(runs.compaction.completed);
      await expect(page.locator('.reply-answer').last()).toContainText('Browser final answer.');
      expect(sent).toEqual(['After manual compaction']);
      const history = await readHistory(request, session.session_id);
      for (const item of before) expect(history.find((row) => row.id === item.id).number).toBe(item.number);
      expect(history.find((row) => row.kind === 'compaction').number).toBeNull();
      expect((await readMessages(request, session.session_id)).some((row) => JSON.stringify(row).includes('/compact'))).toBe(false);
      await marker.getByRole('button', { name: runs.context.details, exact: true }).click();
      const dialog = page.getByRole('dialog', { name: runs.context.details });
      await expect(dialog.locator('.context-text')).toContainText('Write a short factual memory');
      await page.keyboard.press('Escape');
      await marker.getByRole('button', { name: runs.metrics.details, exact: true }).click();
      await expect(page.getByRole('dialog', { name: runs.metrics.details })).toBeVisible();
      await page.keyboard.press('Escape');
      await page.reload();
      await expect(page.locator('[data-compaction-run]')).toContainText(runs.compaction.completed);
      await expect(page.locator('[data-compaction-run] article')).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
      await page.screenshot({ path: info.outputPath('compact-checkpoint.png') });
      expect(errors).toEqual([]);
    });

    for (const outcome of ['cancel', 'fail']) test(`${outcome} pauses queued messages and blocks another command`, async ({ page, request }) => {
      await request.post('/__test__/session', { data: { compaction: outcome === 'cancel' ? 'hold' : 'fail' } });
      await page.goto('/');
      const input = page.locator('.composer textarea');
      await input.fill('/compact'); await input.press('Escape'); await input.press('Enter');
      const marker = page.locator('[data-compaction-run]').last();
      await expect(marker).toContainText(runs.compaction.running);
      await input.fill('Queued while compacting'); await input.press('Enter');
      const queue = page.getByRole('region', { name: chat.queue.label });
      await expect(queue).toContainText('Queued while compacting');
      if (outcome === 'cancel') await marker.getByRole('button', { name: runs.cancel, exact: true }).click();
      else await request.post('/__test__/release-compaction');
      await expect(marker).toContainText(outcome === 'cancel' ? runs.compaction.cancelled : runs.compaction.failed);
      await expect(queue).toContainText(outcome === 'cancel' ? chat.queue.paused.stopped : chat.queue.paused.failed);
      await input.fill('/compact');
      await expect(page.getByRole('listbox').getByRole('option')).toBeDisabled();
      await expect(page.getByText(chat.compactCommand.queued, { exact: true })).toBeVisible();
      await input.press('Enter'); await expect(input).toHaveValue('/compact');
      await expect(page.locator('[data-compaction-run]')).toHaveCount(1);
      await queue.locator('li').last().getByRole('button').last().click();
      await expect(page.getByRole('listbox').getByRole('option')).toBeEnabled();
    });

    test('empty history, attachments, policy and drafts use the command guards', async ({ page, request }) => {
      const session = await (await request.post('/__test__/session')).json();
      await page.goto('/');
      const input = page.locator('.composer textarea');
      await expect(input).toBeEnabled();
      await page.locator('.composer input[type=file]').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('notes') });
      await expect(page.locator('.upload-ready')).toHaveCount(1);
      await input.fill('/compact');
      await expect(page.getByRole('listbox').getByRole('option')).toBeDisabled();
      await expect(page.getByText(chat.compactCommand.attachments, { exact: true })).toBeVisible();
      await input.press('Escape');
      await page.getByRole('button', { name: personas.removeAttachment.replace('{{name}}', 'notes.txt'), exact: true }).click();
      await input.press('Enter');
      const marker = page.locator('[data-compaction-run]');
      await expect(marker).toContainText(runs.compaction.notNeeded);
      await expect(marker.getByRole('button')).toHaveCount(0);
      await request.patch(`/api/sessions/${session.session_id}`, { data: {overrides: {context_policy: { strategy: 'message_window' }}} });
      await input.fill('/compact');
      await expect(page.getByRole('listbox').getByRole('option')).toBeDisabled();
      await expect(page.getByText(chat.compactCommand.policy, { exact: true })).toBeVisible();
      await input.press('Escape');
      await openSidebar(page);
      await page.locator('.sidebar-header').getByRole('button', { name: personas.newSession, exact: true }).click();
      await input.fill('/compact');
      await expect(page.getByRole('listbox').getByRole('option')).toBeDisabled();
      await expect(page.getByText(chat.compactCommand.draft, { exact: true })).toBeVisible();
      expect((await readMessages(request, session.session_id)).length).toBe(0);
    });
  });
}
