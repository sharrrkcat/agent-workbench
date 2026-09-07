import { expect, test, type Page } from '@playwright/test';

async function submit(page: Page, content: string) {
  await expect(page.locator('.composer .send-button')).toBeVisible();
  const input = page.locator('.composer textarea');
  await input.fill(content);
  await expect(page.locator('.composer .send-button')).toBeEnabled();
  await input.press('Enter');
}

async function noOverflow(page: Page) {
  const overflow = await page.evaluate(() => [...document.querySelectorAll('body, .workspace, .chat-view, .message-row, .message-stack, .processing-timeline, .tool-command-details, .approval-details')]
    .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => node.className || node.tagName));
  expect(overflow).toEqual([]);
}

test('scroll following pauses when reading earlier content and resumes explicitly', async ({ page, request }) => {
  await request.post('/__test__/session', { data: {} });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await submit(page, 'scroll-output');
  const body = page.locator('.reply-answer');
  await expect(body).toContainText('Paragraph 18:');
  const view = page.locator('.chat-view');
  await expect.poll(() => view.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThanOrEqual(120);
  await view.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event('scroll')); });
  await expect(body).toContainText('Paragraph 28:');
  expect(await view.evaluate((node) => node.scrollTop)).toBe(0);
  await page.locator('.latest-message-button').click();
  await expect(page.locator('.status-done')).toBeVisible();
  await expect.poll(() => view.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThanOrEqual(120);
});

test('retry replaces the whole reply and deletion removes its tool history', async ({ page, request }) => {
  const response = await request.post('/__test__/session', { data: { long_history: true } });
  const session = await response.json();
  await page.goto('/');
  const original = page.locator('article[data-run-id]');
  const originalId = await original.getAttribute('data-run-id');
  await original.locator('.reply-actions button').nth(1).click();
  await expect(page.locator('.reply-answer')).toHaveText('Browser final answer.');
  await expect(page.locator('.status-done')).toBeVisible();
  expect(await page.locator('article[data-run-id]').getAttribute('data-run-id')).not.toBe(originalId);
  expect((await request.get(`/api/runs/${originalId}`)).status()).toBe(404);
  await expect(page.locator('.tool-command')).toHaveCount(0);
  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('.reply-actions button').last().click();
  await expect(page.locator('article[data-run-id]')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('.message-row.user')).toHaveCount(1);
  await expect(page.locator('article[data-run-id]')).toHaveCount(0);
  expect(await (await request.get(`/api/sessions/${session.session_id}/runs`)).json()).toEqual([]);
});

for (const locale of ['en', 'zh-CN']) {
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`${locale} ${viewport.width}`, () => {
      test.use({ viewport });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((locale) => localStorage.setItem('agent-workbench.locale', locale), locale);
      });

      test('nested history stays compact and long results stay bounded', async ({ page, request }, info) => {
        const response = await request.post('/__test__/session', { data: { long_history: true } });
        expect(response.ok()).toBeTruthy();
        await page.goto('/');
        const reply = page.locator('article[data-run-id]');
        await expect(reply).toHaveCount(1);
        await expect(page.locator('.chat-view .run-panel')).toHaveCount(0);
        await expect(reply.locator('.message-avatar')).toHaveCount(1);
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await expect(reply.locator('.reply-answer')).toContainText('All 12 commands completed.');
        await noOverflow(page);
        await page.screenshot({ path: info.outputPath('completed.png') });
        await reply.locator('.processing-toggle').click();
        await expect(reply.locator('.processing-timeline')).toBeVisible();
        await expect(reply.locator('.tool-group-toggle')).toHaveCount(1);
        await expect(reply.locator('.tool-group-toggle')).toContainText('12');
        await reply.locator('.tool-group-toggle').click();
        await expect(reply.locator('.tool-command-toggle')).toHaveCount(12);
        await expect(reply.locator('.tool-command-details')).toHaveCount(0);
        await reply.locator('.tool-command-toggle').first().click();
        const details = reply.locator('.tool-command-details').first();
        await expect(details).toContainText('large-result:');
        const bounds = await details.locator('pre').last().evaluate((node) => ({ height: node.clientHeight, scrollHeight: node.scrollHeight, width: node.clientWidth, scrollWidth: node.scrollWidth }));
        expect(bounds.height).toBeLessThanOrEqual(viewport.width < 600 ? 240 : 320);
        expect(bounds.scrollHeight).toBeGreaterThan(bounds.height);
        expect(bounds.scrollWidth).toBeGreaterThan(bounds.width);
        await noOverflow(page);
        await page.screenshot({ path: info.outputPath('expanded-commands.png') });
        await page.reload();
        await expect(page.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
      });

      test('both live modes stream the same answer and collapse at completion', async ({ page, request }, info) => {
        await request.post('/__test__/session', { data: {} });
        await page.goto('/');
        await submit(page, 'two-rounds');
        let reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await reply.locator('.processing-toggle').click();
        await expect(reply.locator('.processing-timeline')).toContainText('I will encode first.');
        await expect(reply.locator('.reply-answer')).toContainText('Working on the conversion.');
        await expect(reply.locator('.tool-group-toggle').first()).toBeVisible();
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'true');
        await expect(reply.locator('.processing-timeline')).toContainText('I will decode the encoded text.');
        await page.screenshot({ path: info.outputPath('processing.png') });
        await expect(reply.locator('.reply-answer')).toHaveText('Final result: aGk= decodes to hi.');
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await noOverflow(page);

        await page.goto('/settings?tab=general');
        const label = locale === 'en' ? 'Show full processing history' : '显示完整处理过程';
        await page.getByLabel(label).check();
        await page.getByRole('button', { name: locale === 'en' ? 'Save general settings' : '保存常规设置' }).click();
        await expect.poll(async () => (await (await request.get('/api/settings/general')).json()).show_full_processing).toBe(true);
        await page.locator('.settings-header .icon-button').click();
        await submit(page, 'two-rounds');
        reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'true');
        await expect(reply.locator('.processing-timeline')).toContainText('I will encode first.');
        await reply.locator('.processing-toggle').click();
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await expect(reply.locator('.reply-answer')).toContainText('Working on the conversion.');
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await expect(reply.locator('.reply-answer')).toHaveText('Final result: aGk= decodes to hi.');
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await expect(page.locator('.reply-answer')).toHaveCount(2);
        await expect(reply.locator('.status-done')).toBeVisible();
        await noOverflow(page);
      });

      test('collapsed approvals stay actionable and cancelled output survives reload', async ({ page, request }, info) => {
        await request.post('/__test__/session', { data: {} });
        await page.goto('/');
        await submit(page, 'approval');
        const first = page.locator('article[data-run-id]').first();
        await expect(first.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await expect(first.locator('.approval-details')).toContainText('data/knowledge/note.txt');
        await noOverflow(page);
        await page.screenshot({ path: info.outputPath('approval.png') });
        await first.getByRole('button', { name: locale === 'en' ? 'Approve' : '批准', exact: true }).click();
        await expect(first.locator('.approval-details')).toHaveCount(0);
        await expect(first.locator('.reply-answer')).toHaveText('Browser final answer.');
        await expect(first.locator('.status-done')).toBeVisible();
        await submit(page, 'cancel-stream');
        const second = page.locator('article[data-run-id]').last();
        await expect(second.locator('.reply-answer')).toHaveText('Incomplete streamed answer.');
        await second.locator('.reply-processing-header .danger').click();
        await expect(second.locator('.reply-incomplete')).toBeVisible();
        await page.reload();
        await expect(page.locator('.reply-incomplete')).toBeVisible();
        await expect(page.locator('.reply-answer').last()).toHaveText('Incomplete streamed answer.');
        await expect(page.locator('.processing-toggle').last()).toHaveAttribute('aria-expanded', 'false');
        await noOverflow(page);
        await page.screenshot({ path: info.outputPath('cancelled.png') });
      });
    });
  }
}
