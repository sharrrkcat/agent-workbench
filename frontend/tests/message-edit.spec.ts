import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test(`saved message exits editing before regeneration returns ${locale} ${width}`, async ({ page, request }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const session = await (await request.post('/__test__/session', { data: { long_history: true } })).json();
      const messagesUrl = `**/api/sessions/${session.session_id}/messages`;
      let initialHistory = true;
      await page.route(messagesUrl, async (route) => {
        const response = await route.fetch();
        const messages = await response.json();
        if (initialHistory) {
          messages.find((message: { role: string }) => message.role === 'user').created_at = new Date(Date.now() - 3600000).toISOString();
        }
        await route.fulfill({ json: messages });
      });
      await page.goto('/');
      const user = page.locator('.message-row.user').first();
      await expect(user.locator('time')).toBeAttached();
      const originalTime = await user.locator('time').textContent();
      const edit = user.getByRole('button', { name: locale === 'en' ? 'Edit message' : '编辑消息', exact: true });
      const save = user.getByRole('button', { name: locale === 'en' ? 'Save' : '保存', exact: true });
      await edit.focus();
      await edit.press('Enter');
      await user.locator('textarea').fill('Saved edited question');
      let release!: () => void;
      const gate = new Promise<void>((resolve) => { release = resolve; });
      await page.route('**/api/messages/*/edit', async (route) => {
        const response = await route.fetch();
        await gate;
        await route.fulfill({ response });
      });
      initialHistory = false;
      await save.click();
      try {
        await expect(user.locator('textarea')).toHaveCount(0);
        await expect(save).toHaveCount(0);
        await expect(user.locator('.message')).toHaveText('Saved edited question');
        await expect(edit).toBeDisabled();
      } finally {
        release();
      }
      await expect(edit).toBeEnabled();
      await expect(user.locator('time')).not.toHaveText(originalTime!);
      const savedTime = await user.locator('time').getAttribute('datetime');
      const savedMessages = await (await request.get(`/api/sessions/${session.session_id}/messages`)).json();
      expect(savedTime).toBe(savedMessages.find((message: { role: string }) => message.role === 'user').created_at);
      await page.reload();
      await expect(user.locator('time')).toHaveAttribute('datetime', savedTime!);
      await page.unroute('**/api/messages/*/edit');
      await edit.focus();
      await edit.press('Enter');
      await expect(user.locator('textarea')).toHaveValue('Saved edited question');
      await user.locator('textarea').fill('Keep this failed draft');
      await page.route('**/api/messages/*/edit', (route) => route.fulfill({
        status: 500, json: { detail: 'Edit request failed' },
      }));
      await save.click();
      await expect(user.locator('textarea')).toHaveValue('Keep this failed draft');
      await expect(save).toBeEnabled();
    });
  }
}
