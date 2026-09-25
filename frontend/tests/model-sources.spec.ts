import { chooseOption, fillCombobox, navigateSettings } from './controls';
import fs from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`model sources ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test('manual provider IDs survive failed discovery and local drafts survive subpages', async ({ page, request }, info) => {
        const created = await request.post('/api/models/providers', { data: {
          name: `Source fixture ${locale} ${width}`, connection: { base_url: 'https://provider.test/v1' },
        } });
        const provider = await created.json();
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.route(`**/api/models/providers/${provider.id}/models`, (route) => route.fulfill({
          status: 502, json: { error: { code: 'PROVIDER_ERROR', message: 'Discovery fixture failure' } },
        }));
        await page.goto('/settings?tab=models');
        await expect(page.locator('.settings-content [role="tablist"]')).toHaveCount(0);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        const alias = `runtime-fixture-source-${locale.toLowerCase()}-${width}`;
        await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.unbound);
        await fillCombobox(reference, 'manual-model-id');
        await chooseOption(source, provider.name);
        await expect(reference).toHaveValue('manual-model-id');
        await expect(dialog).toContainText(labels.discoveryUnavailable);
        await expect(dialog.getByLabel(labels.release, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.runtimeDevice, { exact: true })).toHaveCount(0);
        await chooseOption(source, labels.unbound);
        await expect(reference).toHaveValue('manual-model-id');
        await chooseOption(source, provider.name);
        await dialog.getByLabel(labels.name, { exact: true }).fill(`Manual model ${locale} ${width}`);
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        await page.screenshot({ path: info.outputPath('optional-discovery.png') });
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        const row = page.locator('.model-list .model-row').filter({ hasText: alias });
        await expect(row).toContainText(labels.recentRequestState);
        await expect(row.getByRole('button', { name: labels.load, exact: true })).toHaveCount(0);
        await expect(row.getByRole('button', { name: labels.health, exact: true })).toHaveCount(0);
        expect(await row.innerText()).not.toContain(labels.residency);
        const saved = (await (await request.get('/api/models/profiles')).json()).find((item: { alias: string }) => item.alias === alias);
        expect(saved.source).toEqual({ type: 'provider', provider_profile_id: provider.id });
        expect(saved.model_ref).toBe('manual-model-id');
        await row.getByRole('button', { name: labels.edit, exact: true }).click();
        await chooseOption(source, labels.localRuntime);
        await expect(reference).toHaveValue('');
        await expect(dialog.getByLabel(labels.release, { exact: true }).locator('[data-slot="select-value"]')).toHaveText(labels.policy.manual);
        await expect(dialog.getByLabel(labels.runtimeDevice, { exact: true })).toBeVisible();
        await dialog.getByRole('button', { name: labels.close, exact: true }).click();
        await navigateSettings(page, labels.title, labels.localRuntime);
        await page.locator('.runtime-download-settings > [data-slot="collapsible-trigger"]').click();
        const proxy = page.getByLabel(labels.download.http_proxy, { exact: true });
        await proxy.fill('http://127.0.0.1:8899');
        await navigateSettings(page, labels.title, labels.providers);
        await expect(page.getByRole('button', { name: labels.addProvider, exact: true })).toBeVisible();
        await navigateSettings(page, labels.title, labels.localRuntime);
        await expect(proxy).toHaveValue('http://127.0.0.1:8899');
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
        expect(overflow).toBe(false);
      });
    });
  }

  test(`source filtering and stale discovery (${locale})`, async ({ page, request }) => {
    const providers = await Promise.all(['First', 'Second'].map(async (name) => (await request.post('/api/models/providers', { data: {
      name: `${name} discovery ${locale}`, enabled: name === 'First', connection: { base_url: 'https://provider.test/v1' },
    } })).json()));
    let release!: () => void;
    let started!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    const inFlight = new Promise<void>((resolve) => { started = resolve; });
    await page.route(`**/api/models/providers/${providers[0].id}/models`, async (route) => {
      started();
      await pending;
      await route.fulfill({ json: { models: ['obsolete-suggestion'] } });
    });
    await page.route(`**/api/models/providers/${providers[1].id}/models`, (route) => route.fulfill({ json: { models: ['current-suggestion'] } }));
    await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    await page.goto('/settings?tab=models');
    await page.getByRole('button', { name: labels.addModel, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const source = dialog.getByLabel(labels.source, { exact: true });
    const reference = dialog.getByLabel(labels.modelRef, { exact: true });
    await source.click();
    await expect(page.getByRole('option', { name: `${providers[1].name} (${labels.disabled})`, exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await chooseOption(source, providers[0].name);
    await inFlight;
    await fillCombobox(reference, 'previous-model');
    await chooseOption(source, providers[1].name + ` (${labels.disabled})`);
    await expect(reference).toHaveValue('');
    await reference.press('ArrowDown');
    await expect(page.getByRole('option')).toHaveText(['current-suggestion']);
    await page.getByRole('option', { name: 'current-suggestion', exact: true }).click();
    await expect(reference).toHaveValue('current-suggestion');
    await fillCombobox(reference, '');
    const late = page.waitForResponse((response) => response.url().includes(providers[0].id + '/models'));
    release();
    await (await late).finished();
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await reference.press('ArrowDown');
    await expect(page.getByRole('option')).toHaveText(['current-suggestion']);
    await page.keyboard.press('Escape');
    await dialog.getByRole('button', { name: labels.close, exact: true }).click();
    const kind = page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true });
    for (const selected of ['embedding', 'tts', 'reranker', 'image_embedding', 'vision', 'asr']) {
      await chooseOption(kind, labels.kinds[selected]);
      await page.getByRole('button', { name: labels.addModel, exact: true }).click();
      await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
      await source.click();
      await expect(page.getByRole('listbox')).toBeVisible();
      await expect(page.getByRole('option', { name: labels.localRuntime, exact: true })).toHaveCount(1);
      const providerGroup = page.getByRole('group', { name: labels.providers, exact: true });
      await expect(providerGroup).toHaveCount(selected === 'embedding' ? 1 : 0);
      if (selected === 'embedding') await expect.poll(() => providerGroup.getByRole('option').count()).toBeGreaterThan(0);
      await page.keyboard.press('Escape');
      await expect(source).toHaveAttribute('aria-expanded', 'false');
      await dialog.getByRole('button', { name: labels.close, exact: true }).click();
    }
  });
}
