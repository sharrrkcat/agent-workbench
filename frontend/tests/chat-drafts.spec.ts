import { readMessages } from './history';
import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { answerConfirmation, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
const sessions = async (request: APIRequestContext) => (await request.get('/api/sessions')).json();
const send = (page: Page, labels: Record<string, string>) => page.locator('.composer').getByRole('button', { name: labels.send, exact: true });

for (const locale of ['en', 'zh-CN']) {
  const labels = words(locale, 'personas'), llm = words(locale, 'llm');
  for (const width of [1366, 390]) {
    test.describe(`Chat drafts ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page, request }) => {
        await request.post('/__test__/session');
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('new entries share a draft, save settings locally and send attachments once', async ({ page, request }, info) => {
        const before = await sessions(request);
        let creates = 0;
        page.on('request', (r) => { if (r.method() === 'POST' && new URL(r.url()).pathname === '/api/sessions') creates++; });
        await page.goto('/new');
        await expect(send(page, labels)).toBeDisabled();
        await page.locator('.composer textarea').fill('Draft attachment question');
        await page.locator('.composer input[type=file]').setInputFiles({ name: 'draft.txt', mimeType: 'text/plain', buffer: Buffer.from('Draft attachment') });
        await expect(page.locator('.attachment-chip')).toContainText('draft.txt');
        await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: labels.sessionSettings, exact: true });
        await dialog.getByRole('spinbutton', { name: llm.params.temperature, exact: true }).fill('0');
        await expect(dialog.getByRole('combobox', { name: /^(History|历史)$/ })).toHaveCount(0);
        await expect(dialog.getByText(labels.maxMessagesDescription, { exact: true })).toBeVisible();
        await dialog.getByRole('spinbutton', { name: labels.maxMessages, exact: true }).fill('0');
        await dialog.getByRole('spinbutton', { name: labels.maxChars, exact: true }).fill('500');
        await page.screenshot({ path: info.outputPath('history-limits.png') });
        await expect(dialog.getByRole('switch', { name: labels.harnessEnabled, exact: true })).toHaveCount(0);
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toBeHidden();
        await page.locator('.chat-model-select').click();
        await page.getByRole('menuitemcheckbox', { name: labels.harness, exact: true }).click();
        await expect(page.getByRole('menuitemcheckbox', { name: labels.harness, exact: true })).toBeChecked();
        await page.keyboard.press('Escape');
        await openSidebar(page);
        const sidebar = page.locator('.session-sidebar');
        const heading = sidebar.locator('[data-sidebar=group-label]').filter({ hasText: new RegExp(`^${labels.sessions}$`) }).locator('..');
        const quick = heading.getByRole('button', { name: labels.newSession, exact: true });
        if (width === 1366) {
          await page.mouse.move(600, 400);
          await expect(quick).toHaveCSS('opacity', '0');
          await heading.hover();
          await expect(quick).toHaveCSS('opacity', '1');
          await quick.focus();
          await page.keyboard.press('Shift+Tab');
          await page.keyboard.press('Tab');
          await expect(quick).toBeFocused();
          await page.mouse.move(600, 400);
          await expect(quick).toHaveCSS('opacity', '1');
        } else {
          await expect(quick).toHaveCSS('opacity', '1');
          expect((await quick.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        }
        await quick.click();
        await openSidebar(page);
        await sidebar.locator('.sidebar-header').getByRole('button', { name: labels.newSession, exact: true }).click();
        await expect(page.locator('.composer textarea')).toHaveValue('Draft attachment question');
        await expect(page.locator('.attachment-chip')).toContainText('draft.txt');
        expect(creates).toBe(0);
        expect((await sessions(request)).length).toBe(before.length);
        const created = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/sessions' && r.request().method() === 'POST');
        await send(page, labels).click();
        const session = await (await created).json();
        await expect(page).toHaveURL(/\/$/);
        await expect(page.locator('.reply-answer')).toContainText('Browser final answer.');
        expect(creates).toBe(1);
        expect(session.generation).toEqual({ temperature: 0 });
        expect(session.context_policy).toEqual({ max_messages: 0, max_chars: 500, include_attachments: 'explicit' });
        expect(session.harness_enabled).toBe(true);
        await expect(page.locator('.chat-title')).toHaveText('Draft attachmen…');
        await expect(page.locator('.composer textarea')).toHaveValue('');
        await expect(page.locator('.attachment-chip')).toHaveCount(0);
        const messages = await readMessages(request, session.session_id);
        expect(messages.find((m: { role: string }) => m.role === 'user').metadata.attachments[0].name).toBe('draft.txt');
        await expect(page.locator('.composer-context, .context-action')).toHaveCount(0);
        let previous = '0';
        for (const value of ['12', '']) {
          await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
          await expect(dialog.getByRole('spinbutton', { name: labels.maxMessages, exact: true })).toHaveValue(previous);
          await dialog.getByRole('spinbutton', { name: labels.maxMessages, exact: true }).fill(value);
          await dialog.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(dialog).toBeHidden();
          const current = await (await request.get(`/api/sessions/${session.session_id}`)).json();
          expect(current.context_policy).toEqual({ max_messages: value === '' ? null : Number(value), max_chars: 500, include_attachments: 'explicit' });
          previous = value;
        }
        await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
        await expect(dialog.getByRole('spinbutton', { name: labels.maxMessages, exact: true })).toHaveValue('');
        await page.keyboard.press('Escape');
        await page.screenshot({ path: info.outputPath('first-message.png') });
        await request.delete(`/api/sessions/${session.session_id}`);
      });

      test('failed first message preserves the new session, text and attachments for retry', async ({ page, request }) => {
        let attempts = 0, creates = 0;
        page.on('request', (r) => { if (r.method() === 'POST' && new URL(r.url()).pathname === '/api/sessions') creates++; });
        await page.route('**/api/sessions/*/messages', async (route) => {
          if (route.request().method() !== 'POST' || attempts++ > 0) return route.continue();
          await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'TEST_FAILURE', message: 'Try again' } }) });
        });
        await page.goto('/new');
        await page.locator('.composer textarea').fill('Retry with attachment');
        await page.locator('.composer input[type=file]').setInputFiles({ name: 'retry.txt', mimeType: 'text/plain', buffer: Buffer.from('retry') });
        await send(page, labels).click();
        await expect(page).toHaveURL(/\/$/);
        await expect(send(page, labels)).toBeEnabled();
        await expect(page.locator('.composer textarea')).toHaveValue('Retry with attachment');
        await expect(page.locator('.attachment-chip')).toContainText('retry.txt');
        await send(page, labels).click();
        await expect(page.locator('.reply-answer')).toContainText('Browser final answer.');
        expect(creates).toBe(1);
        expect(attempts).toBe(2);
        const session = (await sessions(request)).find((s: { title: string }) => s.title === 'Retry with atta…');
        await request.delete(`/api/sessions/${session.session_id}`);
      });

      test('empty startup and last-session deletion open an unsaved chat', async ({ page, request }) => {
        for (const session of await sessions(request)) await request.delete(`/api/sessions/${session.session_id}`);
        await page.goto('/');
        await expect(page.locator('.composer textarea')).toBeVisible();
        expect(await sessions(request)).toEqual([]);
        await page.locator('.composer textarea').fill('Last conversation');
        await send(page, labels).click();
        await expect(page.locator('.reply-answer')).toContainText('Browser final answer.');
        await openSidebar(page);
        const row = page.locator('.session-sidebar .session-item');
        await row.hover();
        await row.locator('.session-menu').click();
        await page.getByRole('menuitem', { name: labels.deleteSession, exact: true }).click();
        await answerConfirmation(page, true, locale);
        if (width === 390) await page.keyboard.press('Escape');
        await expect(page.locator('.chat-title')).toHaveText(labels.newSession);
        await expect(page.locator('.composer textarea')).toHaveValue('');
        expect(await sessions(request)).toEqual([]);
      });
    });
  }
}
