import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { chooseOption, fillCombobox } from './controls';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`Image generation ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test('provider-only source, discovery, defaults and profile CRUD', async ({ page, request }, info) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        const provider = await (await request.post('/api/models/providers', { data: {
          name: `Image provider ${locale} ${width}`, connection: { base_url: 'https://image.test/v1' },
        } })).json();
        let discovery = true;
        await page.route(`**/api/models/providers/${provider.id}/models`, (route) => route.fulfill(discovery
          ? { json: { models: ['discovered-image'] } }
          : { status: 502, json: { error: { code: 'PROVIDER_ERROR', message: 'Discovery unavailable' } } }));
        await page.goto('/settings?tab=models&view=image_generation');
        await expect(page).toHaveURL(/view=image_generation/);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        await expect(source).toContainText(labels.selectModelSource);
        await expect(save).toBeDisabled();
        await source.click();
        const local = page.getByRole('option', { name: labels.localRuntime, exact: true });
        await expect(local).toBeVisible();
        await expect(local).toBeDisabled();
        await local.click({ force: true });
        await expect(source).toContainText(labels.selectModelSource);
        await page.getByRole('option', { name: provider.name, exact: true }).click();
        await expect(save).toBeEnabled();
        await expect(dialog).toContainText(labels.imageGeneration.providerOnly);
        for (const name of [labels.release, labels.runtimeDevice])
          await expect(dialog.getByLabel(name, { exact: true })).toHaveCount(0);
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        await reference.press('ArrowDown');
        await page.getByRole('option', { name: 'discovered-image', exact: true }).click();
        await expect(reference).toHaveValue('discovered-image');
        const alias = `image-${locale.toLowerCase()}-${width}`;
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        const count = dialog.getByLabel(labels.imageGeneration.n, { exact: true });
        const size = dialog.getByLabel(labels.imageGeneration.size, { exact: true });
        await expect(count).toHaveValue('1');
        await expect(size).toHaveValue('');
        for (const key of ['quality', 'style', 'response_format'])
          await expect(dialog.getByLabel(labels.imageGeneration[key], { exact: true })).toContainText(labels.imageGeneration.providerDefault);
        await count.fill('0');
        expect(await count.evaluate((node: HTMLInputElement) => node.checkValidity())).toBe(false);
        await count.fill('2');
        await size.fill('1024x1024');
        await chooseOption(dialog.getByLabel(labels.imageGeneration.quality, { exact: true }), labels.imageGeneration.values.hd);
        await chooseOption(dialog.getByLabel(labels.imageGeneration.style, { exact: true }), labels.imageGeneration.values.vivid);
        await chooseOption(dialog.getByLabel(labels.imageGeneration.response_format, { exact: true }), labels.imageGeneration.values.b64_json);
        await expect(page.locator('[data-slot="select-content"]:visible')).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('image-generation-settings.png') });
        expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
        await save.click();
        await expect(dialog).toHaveCount(0);
        const profiles = await (await request.get('/api/models/profiles?kind=image_generation')).json();
        const profile = profiles.find((item: { alias: string }) => item.alias === alias);
        expect(profile.source).toEqual({ type: 'provider', provider_profile_id: provider.id });
        expect(profile.parameters).toEqual({ n: 2, size: '1024x1024', quality: 'hd', style: 'vivid', response_format: 'b64_json' });
        const card = page.locator('.model-profile-card').filter({ has: page.getByText(alias, { exact: true }) });
        await expect(card).toContainText(provider.name);
        await expect(card).toContainText(labels.recentRequestState);
        for (const name of [labels.load, labels.health, labels.unload])
          await expect(card.getByRole('button', { name, exact: true })).toHaveCount(0);
        await card.getByRole('switch').click();
        await expect(card.getByRole('switch')).not.toBeChecked();
        discovery = false;
        await card.getByRole('button', { name: labels.edit, exact: true }).click();
        await expect(dialog).toContainText(labels.discoveryUnavailable);
        await expect(count).toHaveValue('2');
        await expect(size).toHaveValue('1024x1024');
        await fillCombobox(reference, 'manual-image');
        await count.fill('1');
        await size.fill('');
        for (const key of ['quality', 'style', 'response_format']) {
          const control = dialog.getByLabel(labels.imageGeneration[key], { exact: true });
          await control.click();
          await expect(control).toHaveAttribute('aria-controls', /.+/);
          const list = page.locator(`[id="${await control.getAttribute('aria-controls')}"]`);
          await list.getByRole('option', { name: labels.imageGeneration.providerDefault, exact: true }).click();
          await expect(control).toHaveAttribute('aria-expanded', 'false');
          await expect(list).toBeHidden();
        }
        await save.click();
        await expect(dialog).toHaveCount(0);
        const edited = await (await request.get(`/api/models/profiles/${profile.id}`)).json();
        expect(edited.model_ref).toBe('manual-image');
        expect(edited.parameters).toEqual({ n: 1 });
        expect(edited.enabled).toBe(false);
        await page.reload();
        await expect(card.getByRole('switch')).not.toBeChecked();
        await card.getByRole('button', { name: labels.delete, exact: true }).click();
        await expect(card).toHaveCount(0);
        expect((await request.delete(`/api/models/providers/${provider.id}`)).ok()).toBe(true);
      });
    });
  }
}
