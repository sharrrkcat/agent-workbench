import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test(`saved message exits editing before regeneration returns ${locale} ${width}`, async ({ page, request }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      await request.post('/__test__/session', { data: { long_history: true } });
      await page.goto('/');
      const user = page.locator('.message-row.user').first();
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
