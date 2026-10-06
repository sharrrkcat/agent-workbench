import fs from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { modelKinds, type ModelProfile } from '../src/types/models';
import { answerConfirmation, chooseOption, fillCombobox, navigateModelSettings, navigateSettings, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(
  fs.readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));

async function openCreation(page: Page, label: string) {
  await openSidebar(page);
  const add = page.locator('.settings-sidebar').getByRole('button', { name: label, exact: true });
  await expect(add).toBeEnabled();
  await add.focus();
  await add.click();
}

for (const locale of ['en', 'zh-CN']) {
  const llm = words(locale, 'llm'), settings = words(locale, 'settings'), knowledge = words(locale, 'knowledge');
  for (const width of [1366, 390]) {
    test.describe(`Model creation ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('empty categories, header actions and every model kind can be created and removed', async ({ page, request }, info) => {
        test.setTimeout(90000);
        let profiles: ModelProfile[] = [];
        const created: string[] = [];
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        const provider = await (await request.post('/api/models/providers', { data: {
          name: `Creation provider ${locale} ${width}`, connection: { base_url: 'https://creation.test/v1' },
        } })).json();
        await page.route(`**/api/models/providers/${provider.id}/models`, (route) => route.fulfill({ json: { models: [] } }));
        await page.route('**/api/models/profiles', async (route) => {
          if (route.request().method() === 'GET') return route.fulfill({ json: profiles });
          const response = await route.fetch();
          if (response.ok()) {
            const profile = await response.json();
            profiles.push(profile); created.push(profile.id);
          }
          await route.fulfill({ response });
        });
        await page.route('**/api/models/profiles/*', async (route) => {
          const response = await route.fetch();
          if (response.ok()) {
            const id = route.request().url().split('/').at(-1);
            if (route.request().method() === 'DELETE') profiles = profiles.filter((profile) => profile.id !== id);
            if (route.request().method() === 'PATCH') {
              const profile = await response.json();
              profiles = profiles.map((item) => item.id === id ? profile : item);
            }
          }
          await route.fulfill({ response });
        });
        try {
          await page.goto('/settings?tab=general');
          await openSidebar(page);
          const menu = page.locator('.settings-sidebar').getByRole('list', { name: settings.models, exact: true });
          const toggle = menu.locator('[data-settings-menu="models"]');
          const add = menu.getByRole('button', { name: llm.addAnyModel, exact: true });
          await expect(add).toBeEnabled();
          await expect(toggle).toHaveAttribute('aria-expanded', 'false');
          if (width === 1366) {
            await page.locator('.settings-heading').hover();
            await expect(add).toHaveCSS('opacity', '0');
            await toggle.hover();
          }
          await expect(add).toHaveCSS('opacity', '1');
          await toggle.click();
          await expect(menu.locator('[data-settings-page]')).toHaveCount(1);
          await expect(menu.getByRole('button', { name: llm.dashboard, exact: true })).toBeVisible();
          await toggle.click();
          await toggle.focus();
          await toggle.press('Tab');
          await expect(add).toBeFocused();
          await add.press('Enter');
          const dialog = page.getByRole('dialog', { name: llm.addModel, exact: true });
          await expect(dialog.getByLabel(llm.kind, { exact: true })).toContainText(llm.kinds.llm);
          if (width === 1366) await expect(page.locator('[data-settings-menu="models"]')).toHaveAttribute('aria-expanded', 'false');
          else await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'false');
          await page.keyboard.press('Escape');
          await expect(dialog).toHaveCount(0);
          await expect(width === 1366 ? add : page.locator('[data-sidebar="trigger"]')).toBeFocused();

          for (const kind of modelKinds) {
            await openCreation(page, llm.addAnyModel);
            await chooseOption(dialog.getByLabel(llm.kind, { exact: true }), llm.kinds[kind]);
            if (kind === 'image_generation') {
              await expect(dialog.getByRole('button', { name: llm.save, exact: true })).toBeDisabled();
              await chooseOption(dialog.getByLabel(llm.source, { exact: true }), provider.name);
            }
            const name = `Created ${kind} ${locale} ${width}`, alias = `created-${kind}-${locale.toLowerCase()}-${width}`;
            await dialog.getByLabel(llm.name, { exact: true }).fill(name);
            await dialog.getByLabel(llm.alias, { exact: true }).fill(alias);
            await fillCombobox(dialog.getByLabel(llm.modelRef, { exact: true }), `manual/${kind}`);
            if (kind === 'llm') await page.screenshot({ path: info.outputPath('unified-model-dialog.png'), animations: 'disabled' });
            expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
            await dialog.getByRole('button', { name: llm.save, exact: true }).click();
            await expect(dialog).toHaveCount(0);
            await expect(page).toHaveURL(`/settings?tab=models&view=${kind}`);
            const card = page.getByRole('group', { name, exact: true });
            await expect(card).toBeVisible();
            expect(profiles[0].kind).toBe(kind);
            await card.getByRole('switch').click();
            await expect(card.getByRole('switch')).not.toBeChecked();
            await openSidebar(page);
            await expect(toggle).toHaveAttribute('aria-expanded', 'true');
            await expect(menu.locator('[data-settings-page]')).toHaveCount(2);
            await expect(menu.getByRole('button', { name: llm.kinds[kind], exact: true })).toHaveAttribute('aria-current', 'page');
            if (kind === 'llm') {
              if (width === 1366) await toggle.hover();
              await expect(page.locator('.settings-sidebar')).toHaveCSS('opacity', '1');
              await expect.poll(async () => (await page.locator('.settings-sidebar').boundingBox())!.x).toBe(0);
              await page.screenshot({ path: info.outputPath('models-sidebar.png'), animations: 'disabled' });
            }
            if (width === 390) await page.keyboard.press('Escape');
            await card.getByRole('button', { name: llm.delete, exact: true }).click();
            await expect(card).toHaveCount(0);
            await expect(page.locator('.settings-view:visible').getByText(llm.emptyModels, { exact: true })).toBeVisible();
            await openSidebar(page);
            await expect(menu.locator('[data-settings-page]')).toHaveCount(1);
            if (width === 390) await page.keyboard.press('Escape');
          }
          // An empty category still has a usable direct URL and a fixed-kind shortcut.
          await page.goto('/settings?tab=models&view=asr');
          await page.getByRole('button', { name: llm.addModel, exact: true }).click();
          await expect(dialog.getByLabel(llm.kind, { exact: true })).toBeDisabled();
          await expect(dialog.getByLabel(llm.kind, { exact: true })).toContainText(llm.kinds.asr);
          expect(errors).toEqual([]);
        } finally {
          for (const id of created) await request.delete(`/api/models/profiles/${id}`);
          await request.delete(`/api/models/providers/${provider.id}`);
        }
      });

      test('kind switching resets source fields, ignores late suggestions and preserves failed saves', async ({ page, request }) => {
        let releaseInventory!: () => void;
        const inventory = new Promise<void>((resolve) => { releaseInventory = resolve; });
        await page.route('**/api/models/inventory?kind=llm', async (route) => {
          await inventory;
          await route.fulfill({ json: [{ model_ref: 'old-llm' }] });
        });
        await page.route('**/api/models/inventory?kind=tts', (route) => route.fulfill({ json: [{ model_ref: 'tts/current' }] }));
        await page.goto('/settings?tab=models&view=dashboard');
        await navigateSettings(page, settings.general);
        await openCreation(page, llm.addAnyModel);
        const dialog = page.getByRole('dialog', { name: llm.addModel, exact: true });
        const kind = dialog.getByLabel(llm.kind, { exact: true });
        const reference = dialog.getByLabel(llm.modelRef, { exact: true });
        await dialog.getByLabel(llm.name, { exact: true }).fill('Retained identity');
        const alias = `switch-kind-${locale.toLowerCase()}-${width}`;
        await dialog.getByLabel(llm.alias, { exact: true }).fill(alias);
        await fillCombobox(reference, 'llms/old');
        await chooseOption(kind, llm.kinds.image_generation);
        await expect(reference).toHaveValue('');
        await expect(dialog.getByLabel(llm.source, { exact: true })).toContainText(llm.selectModelSource);
        await chooseOption(kind, llm.kinds.tts);
        await expect(dialog.getByLabel(llm.source, { exact: true })).toContainText(llm.localRuntime);
        await expect(dialog.getByLabel(llm.name, { exact: true })).toHaveValue('Retained identity');
        const late = page.waitForResponse('**/api/models/inventory?kind=llm');
        releaseInventory();
        await (await late).finished();
        await reference.press('ArrowDown');
        await expect(page.getByRole('option')).toHaveText(['tts/current']);
        await page.getByRole('option', { name: 'tts/current', exact: true }).click();
        await page.route('**/api/models/profiles', async (route) => {
          if (route.request().method() !== 'POST') return route.continue();
          await route.fulfill({ status: 409, json: { error: { code: 'MODEL_CONFLICT', message: 'Creation fixture conflict' } } });
        });
        const save = dialog.getByRole('button', { name: llm.save, exact: true });
        await save.click();
        await expect(dialog.getByRole('alert')).toContainText('Creation fixture conflict');
        await expect(reference).toHaveValue('tts/current');
        await expect(dialog.getByLabel(llm.alias, { exact: true })).toHaveValue(alias);
        await page.unroute('**/api/models/profiles');
        let releaseSave!: () => void;
        const pending = new Promise<void>((resolve) => { releaseSave = resolve; });
        let created: ModelProfile | undefined;
        await page.route('**/api/models/profiles', async (route) => {
          if (route.request().method() !== 'POST') return route.continue();
          await pending;
          const response = await route.fetch();
          created = await response.json();
          await route.fulfill({ response });
        });
        try {
          await save.click();
          await expect(save).toBeDisabled();
          await expect(kind).toBeDisabled();
          await page.keyboard.press('Escape');
          await expect(dialog).toBeVisible();
          await page.goBack();
          await expect(page).toHaveURL('/settings?tab=general');
          releaseSave();
          await expect(page).toHaveURL('/settings?tab=models&view=tts');
          await expect(dialog).toHaveCount(0);
        } finally {
          releaseSave();
          if (created) await request.delete(`/api/models/profiles/${created.id}`);
        }
      });

      test('creation reveals the list without discarding a retained category draft', async ({ page, request }) => {
        await page.goto('/settings?tab=models&view=dashboard');
        await navigateModelSettings(page, 'llm');
        await page.getByRole('button', { name: llm.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: llm.addModel, exact: true });
        await dialog.getByLabel(llm.name, { exact: true }).fill('Retained category draft');
        await page.goBack();
        await expect(dialog).toHaveCount(0);
        await openCreation(page, llm.addAnyModel);
        const alias = `draft-retention-${locale.toLowerCase()}-${width}`;
        await dialog.getByLabel(llm.name, { exact: true }).fill('New global model');
        await dialog.getByLabel(llm.alias, { exact: true }).fill(alias);
        await fillCombobox(dialog.getByLabel(llm.modelRef, { exact: true }), 'llms/manual');
        await dialog.getByRole('button', { name: llm.save, exact: true }).click();
        await expect(page).toHaveURL('/settings?tab=models&view=llm');
        await expect(dialog).toHaveCount(0);
        const profiles = await (await request.get('/api/models/profiles')).json();
        const created = profiles.find((profile: ModelProfile) => profile.alias === alias);
        try {
          await expect(page.getByRole('group', { name: 'New global model', exact: true })).toBeVisible();
          await navigateModelSettings(page, 'dashboard');
          await navigateModelSettings(page, 'llm');
          await expect(dialog.getByLabel(llm.name, { exact: true })).toHaveValue('Retained category draft');
        } finally { await request.delete(`/api/models/profiles/${created.id}`); }
      });

      test('creating from unsaved settings keeps the existing departure confirmation', async ({ page, request }) => {
        await page.goto('/settings?tab=knowledge&view=settings');
        const chunk = page.getByLabel(knowledge.chunkSize, { exact: true });
        await expect(chunk).toBeVisible();
        const value = String(Number(await chunk.inputValue()) + 1);
        await chunk.fill(value);
        await openCreation(page, llm.addAnyModel);
        const dialog = page.getByRole('dialog', { name: llm.addModel, exact: true });
        const alias = `guarded-creation-${locale.toLowerCase()}-${width}`;
        await dialog.getByLabel(llm.name, { exact: true }).fill('Guarded creation');
        await dialog.getByLabel(llm.alias, { exact: true }).fill(alias);
        await fillCombobox(dialog.getByLabel(llm.modelRef, { exact: true }), 'llms/manual');
        await dialog.getByRole('button', { name: llm.save, exact: true }).click();
        await answerConfirmation(page, false, locale);
        await expect(page).toHaveURL('/settings?tab=knowledge&view=settings');
        await expect(chunk).toHaveValue(value);
        const profiles = await (await request.get('/api/models/profiles')).json();
        const created = profiles.find((profile: ModelProfile) => profile.alias === alias);
        expect(created).toBeTruthy();
        await request.delete(`/api/models/profiles/${created.id}`);
      });
    });
  }
}
