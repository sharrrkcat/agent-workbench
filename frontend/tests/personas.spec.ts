import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse } from '@playwright/test';
import { USER_PERSONA_ID } from '../src/types/chat';
import { answerConfirmation } from './controls';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=', 'base64');
async function json(response: Promise<APIResponse>) {
  const result = await response;
  expect(result.ok(), await result.text()).toBe(true);
  return result.json();
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  test.describe(`Personas ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('independent user identities support background/avatar CRUD and protect User', async ({ page, request }, info) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const user = await json(request.get(`/api/personas/${USER_PERSONA_ID}`));
      let personaId = '';
      try {
        await page.goto('/settings?tab=personas');
        const userRow = page.locator('.persona-row').filter({ hasText: user.name });
        await expect(userRow.getByRole('button', { name: labels.deleteNamed.replace('{{name}}', user.name), exact: true })).toHaveCount(0);
        await userRow.getByRole('button', { name: labels.editNamed.replace('{{name}}', user.name), exact: true }).click();
        const editor = page.getByRole('dialog');
        await editor.getByLabel(labels.background, { exact: true }).fill('Unsaved User background');
        await page.keyboard.press('Escape');
        await answerConfirmation(page, false, locale);
        await expect(editor.getByLabel(labels.background, { exact: true })).toHaveValue('Unsaved User background');
        await page.keyboard.press('Escape');
        await answerConfirmation(page, true, locale);
        await expect(editor).toBeHidden();
        expect((await json(request.get(`/api/personas/${USER_PERSONA_ID}`))).background).toBe(user.background);
        await page.getByRole('button', { name: labels.add, exact: true }).click();
        await editor.getByLabel(labels.name, { exact: true }).fill('Independent user');
        await editor.getByLabel(labels.background, { exact: true }).fill('Prefers concise answers.');
        await expect(editor.getByRole('tablist')).toHaveCount(0);
        await editor.locator('input[type="file"]').setInputFiles({ name: 'avatar.png', mimeType: 'image/png', buffer: png });
        await expect(editor.locator('[data-slot="avatar-image"]')).toBeVisible();
        const created = page.waitForResponse((response) => response.url().endsWith('/api/personas') && response.request().method() === 'POST');
        await editor.getByRole('button', { name: labels.save, exact: true }).click();
        const response = await created;
        expect(response.ok()).toBe(true);
        const persona = await response.json();
        personaId = persona.id;
        expect(persona).toMatchObject({ name: 'Independent user', background: 'Prefers concise answers.', is_protected: false });
        expect(persona).not.toHaveProperty('collection');
        await expect(editor).toBeHidden();
        await page.reload();
        const row = page.locator('.persona-row').filter({ hasText: 'Independent user' });
        await expect(row.locator('[data-slot="avatar-image"]')).toBeVisible();
        await row.getByRole('button', { name: labels.editNamed.replace('{{name}}', 'Independent user'), exact: true }).click();
        await expect(editor.getByLabel(labels.background, { exact: true })).toHaveValue('Prefers concise answers.');
        await editor.getByRole('button', { name: labels.removeAvatar, exact: true }).click();
        await editor.getByLabel(labels.name, { exact: true }).fill('Renamed user');
        await editor.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(editor).toBeHidden();
        const renamed = page.locator('.persona-row').filter({ hasText: 'Renamed user' });
        await expect(renamed.locator('[data-slot="avatar-image"]')).toHaveCount(0);
        expect((await json(request.get(`/api/personas/${personaId}`))).avatar_attachment_id).toBeNull();
        await page.screenshot({ path: info.outputPath('personas.png') });
        await renamed.getByRole('button', { name: labels.deleteNamed.replace('{{name}}', 'Renamed user'), exact: true }).click();
        await answerConfirmation(page, true, locale);
        await expect(renamed).toHaveCount(0);
        expect((await request.get(`/api/personas/${personaId}`)).status()).toBe(404);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(errors).toEqual([]);
      } finally { if (personaId) await request.delete(`/api/personas/${personaId}`); }
    });
  });
}
