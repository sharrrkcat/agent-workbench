import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { openSidebar } from './controls';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`Character editor ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });

      test('Normal creation, sidebar and settings render and save without runtime errors', async ({ page, request }, info) => {
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await request.post('/__test__/session');
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        let characterId = '';
        const name = `Character ${locale} ${width}`;
        try {
          await page.goto('/');
          await openSidebar(page);
          await page.getByRole('button', { name: labels.newCharacter, exact: true }).click();
          const dialog = page.getByRole('dialog', { name: labels.newCharacter, exact: true });
          await dialog.getByRole('button', { name: labels.characterKinds.normal, exact: true }).click();
          await expect(dialog.getByLabel(labels.characterName, { exact: true })).toBeVisible();
          expect(errors).toEqual([]);
          await dialog.getByLabel(labels.characterName, { exact: true }).fill(name);
          await dialog.getByRole('tab', { name: labels.configuration, exact: true }).click();
          await expect(dialog.getByLabel(labels.defaultPersona, { exact: true })).toBeVisible();
          await dialog.getByRole('tab', { name: labels.resources, exact: true }).click();
          await expect(dialog.getByText(labels.mountsInactive, { exact: true })).toBeVisible();
          const created = page.waitForResponse((response) => response.url().endsWith('/api/characters') && response.request().method() === 'POST');
          await dialog.getByRole('button', { name: labels.save, exact: true }).click();
          const response = await created;
          expect(response.ok()).toBe(true);
          characterId = (await response.json()).id;
          await expect(dialog).toBeHidden();
          await expect(page.locator('.composer textarea')).toBeVisible();

          await openSidebar(page);
          const character = page.locator(`[data-character-id="${characterId}"]`);
          const heading = character.locator('.character-select');
          const empty = character.getByText(labels.noCharacterSessions, { exact: true });
          await expect(character.locator('.group\\/character-heading button')).toHaveCount(3);
          await expect(character.locator('[data-sidebar="menu-action"][data-slot="collapsible-trigger"]')).toHaveCount(0);
          await expect(empty).toBeVisible();
          await expect(empty).toHaveCSS('font-size', '12px');
          await heading.click();
          await openSidebar(page);
          await expect(heading).toHaveAttribute('aria-expanded', 'false');
          await expect(empty).toBeHidden();
          await heading.click();
          await openSidebar(page);
          await expect(heading).toHaveAttribute('aria-expanded', 'true');
          await expect(empty).toBeVisible();
          await page.screenshot({ path: info.outputPath('character-sidebar.png') });
          await character.getByRole('button', { name: labels.characterActions.replace('{{name}}', name), exact: true }).click();
          await page.getByRole('menuitem', { name: labels.characterSettings, exact: true }).click();
          await expect(page).toHaveURL(new RegExp(`/characters/${characterId}/settings$`));
          await page.getByRole('button', { name: labels.characterCards.editProfile, exact: true }).click();
          const profile = page.getByRole('form', { name: labels.characterCards.profile, exact: true });
          const drawer = page.getByRole('dialog', { name: labels.characterCards.profile, exact: true });
          await expect(page.getByLabel(labels.characterName, { exact: true })).toHaveValue(name);
          expect(errors).toEqual([]);
          await page.getByLabel(labels.systemPrompt, { exact: true }).fill('Saved Character instructions.');
          await profile.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(profile.getByRole('status')).toHaveText(labels.saved);
          await drawer.getByRole('button', { name: labels.close, exact: true }).click();
          await expect(drawer).toBeHidden();
          await page.reload();
          await expect(page.locator('[data-profile-prompt]')).toHaveText('Saved Character instructions.');
          await expect(page.locator('.character-settings').getByRole('tablist')).toHaveCount(0);
          await expect(page.getByText(labels.characterCards.resourceUnavailable, { exact: true })).toHaveCount(2);
          await page.screenshot({ path: info.outputPath('character-settings.png') });
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
          expect(errors).toEqual([]);
        } finally {
          if (characterId) await request.delete(`/api/characters/${characterId}`);
        }
      });
    });
  }
}
