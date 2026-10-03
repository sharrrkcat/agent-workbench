import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { openSidebar } from './controls';
import { readMessages } from './history';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
const file = { name: 'queued.txt', mimeType: 'text/plain', buffer: Buffer.from('Queue attachment') };

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const labels = words(locale, 'personas'), chat = words(locale, 'chat'), q = chat.queue;
  test.describe(`Message queue ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    });

    test('FIFO, original-position editing, attachments, scroll, stop and session navigation', async ({ page, request }, info) => {
      const otherTitle = `Queue other ${locale} ${width}`, originTitle = `Queue origin ${locale} ${width}`;
      await request.post('/api/sessions', { data: { title: otherTitle } });
      const session = await (await request.post('/__test__/session')).json();
      await request.patch(`/api/sessions/${session.session_id}`, { data: { title: originTitle } });
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message));
      await page.goto('/');
      const input = page.locator('.composer textarea'), composer = page.locator('.composer');
      const queue = page.getByRole('region', { name: q.label });
      const rows = queue.locator('li');
      const posts: string[] = [];
      page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/messages')) posts.push(r.postDataJSON().content); });
      await input.fill('cancel-stream'); await input.press('Enter');
      await expect(input).toBeEnabled();
      await expect(composer.getByRole('button', { name: labels.cancel, exact: true })).toBeVisible();
      await input.fill('first'); await input.press('Enter');
      await input.fill('second');
      await page.locator('.composer input[type=file]').setInputFiles(file);
      await expect(page.locator('.upload-ready')).toHaveCount(1);
      await composer.getByRole('button', { name: q.add, exact: true }).click();
      for (let i = 0; i < 7; i++) { await input.fill(`extra ${i}`); await input.press('Enter'); }
      await expect(rows).toHaveCount(9);
      const headId = await rows.first().getAttribute('data-queue-id');
      const measurements = await queue.locator('ol').evaluate((node) => ({ height: node.clientHeight, content: node.scrollHeight }));
      expect(measurements.height).toBeLessThanOrEqual(Math.min(240, (width === 390 ? 844 : 900) * .25));
      expect(measurements.content).toBeGreaterThan(measurements.height);
      expect((await queue.boundingBox())!.y + (await queue.boundingBox())!.height).toBeLessThanOrEqual((await composer.boundingBox())!.y);
      if (width === 390) expect((await rows.first().getByRole('button').first().boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await page.screenshot({ path: info.outputPath('queue-stacked.png') });
      for (let i = 0; i < 7; i++) await rows.last().getByRole('button').last().click();
      await input.fill('discard existing draft');
      await page.locator('.composer input[type=file]').setInputFiles({ ...file, name: 'discard.txt' });
      await expect(page.locator('.upload-ready')).toHaveCount(1);
      await rows.first().getByRole('button').first().focus(); await page.keyboard.press('Enter');
      await expect(input).toBeFocused(); await expect(input).toHaveValue('first');
      await expect(page.locator('.attachment-strip')).toHaveCount(0);
      await expect(rows.nth(1).getByRole('button').first()).toBeDisabled();
      await input.fill('edited first'); await input.press('Shift+Enter'); await input.press('x');
      await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true });
      await expect(rows.first()).toHaveAttribute('data-editing', 'true');
      await expect(input).toHaveValue('edited first\nx');
      await openSidebar(page);
      await page.locator('.session-sidebar').getByRole('button', { name: otherTitle, exact: true }).click();
      await expect(input).toHaveValue(''); await expect(queue).toHaveCount(0);
      await openSidebar(page);
      await page.locator('.session-sidebar').getByRole('button', { name: originTitle, exact: true }).click();
      await expect(input).toHaveValue('edited first\nx'); await expect(rows).toHaveCount(2);
      await expect(rows.first()).toHaveAttribute('data-queue-id', headId!);
      await composer.getByRole('button', { name: labels.cancel, exact: true }).click();
      await expect(page.locator('.status-cancelled')).toBeVisible();
      await expect(queue).toContainText(q.paused.stopped);
      await queue.getByRole('button', { name: q.resume, exact: true }).click();
      await expect(queue).toContainText(q.waitingEdit);
      expect(posts).toEqual(['cancel-stream']);
      await page.screenshot({ path: info.outputPath('queue-editing.png') });
      await composer.getByRole('button', { name: q.save, exact: true }).click();
      await expect(queue).toHaveCount(0);
      await expect(page.locator('.status-done')).toHaveCount(2);
      expect(posts).toEqual(['cancel-stream', 'edited first\nx', 'second']);
      const messages = await readMessages(request, session.session_id);
      expect(messages.filter((m: { role: string }) => m.role === 'user').at(-1).metadata.attachments[0].name).toBe(file.name);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
      expect(errors).toEqual([]);
    });

    test('approval allows queueing; deleting an edit clears it; refresh drops the memory queue', async ({ page, request }, info) => {
      const session = await (await request.post('/__test__/session')).json();
      await page.goto('/');
      const input = page.locator('.composer textarea'), queue = page.getByRole('region', { name: q.label });
      await input.fill('approval'); await input.press('Enter');
      await expect(page.locator('.approval-details')).toBeVisible();
      await input.fill('queued after approval'); await input.press('Enter');
      await expect(queue.locator('li')).toHaveCount(1);
      await queue.locator('li').getByRole('button').first().click();
      await page.locator('.composer input[type=file]').setInputFiles(file);
      await expect(page.locator('.upload-ready')).toHaveCount(1);
      await queue.locator('li').getByRole('button').last().click();
      await expect(queue).toHaveCount(0); await expect(input).toHaveValue('');
      await expect(page.locator('.attachment-strip')).toHaveCount(0);
      await input.fill('discard on reload'); await input.press('Enter');
      await expect(queue.locator('li')).toHaveCount(1);
      await page.screenshot({ path: info.outputPath('queue-approval.png') });
      await page.reload();
      await expect(page.locator('.approval-details')).toBeVisible(); await expect(queue).toHaveCount(0);
      expect((await readMessages(request, session.session_id)).filter((m: { role: string }) => m.role === 'user')).toHaveLength(1);
    });
  });
}
