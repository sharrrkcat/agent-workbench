import fs from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`model sources ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 } });
      test('manual provider IDs survive failed discovery and local drafts survive tabs', async ({ page, request }, info) => {
        const created = await request.post('/api/models/providers', { data: {
          name: `Source fixture ${locale} ${width}`, connection: { base_url: 'https://provider.test/v1' },
        } });
        const provider = await created.json();
        await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
        await page.route(`**/api/models/providers/${provider.id}/models`, (route) => route.fulfill({
          status: 502, json: { error: { code: 'PROVIDER_ERROR', message: 'Discovery fixture failure' } },
        }));
        await page.goto('/settings?tab=models');
        await expect(page.locator('.model-tabs [role="tab"]')).toHaveCount(4);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        const alias = `runtime-fixture-source-${locale.toLowerCase()}-${width}`;
        await expect(source).toHaveValue('');
        await reference.fill('manual-model-id');
        await source.selectOption(`provider:${provider.id}`);
        await expect(reference).toHaveValue('manual-model-id');
        await expect(dialog).toContainText(labels.discoveryUnavailable);
        await expect(dialog.getByLabel(labels.release, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.runtimeDevice, { exact: true })).toHaveCount(0);
        await source.selectOption('');
        await expect(reference).toHaveValue('manual-model-id');
        await source.selectOption(`provider:${provider.id}`);
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
        await source.selectOption('local');
        await expect(reference).toHaveValue('');
        await expect(dialog.getByLabel(labels.release, { exact: true })).toHaveValue('manual');
        await expect(dialog.getByLabel(labels.runtimeDevice, { exact: true })).toBeVisible();
        await dialog.getByRole('button', { name: labels.close, exact: true }).click();
        await page.getByRole('tab', { name: labels.localRuntime, exact: true }).click();
        await page.locator('.runtime-download-settings summary').click();
        const proxy = page.getByLabel(labels.download.http_proxy, { exact: true });
        await proxy.fill('http://127.0.0.1:8899');
        await page.getByRole('tab', { name: labels.providers, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.addProvider, exact: true })).toBeVisible();
        await page.getByRole('tab', { name: labels.localRuntime, exact: true }).click();
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
    await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
    await page.goto('/settings?tab=models');
    await page.getByRole('button', { name: labels.addModel, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const source = dialog.getByLabel(labels.source, { exact: true });
    const reference = dialog.getByLabel(labels.modelRef, { exact: true });
    await expect(source.locator(`option[value="provider:${providers[1].id}"]`)).toContainText(labels.disabled);
    await source.selectOption(`provider:${providers[0].id}`);
    await inFlight;
    await reference.fill('previous-model');
    await source.selectOption(`provider:${providers[1].id}`);
    await expect(reference).toHaveValue('');
    await expect(dialog.locator('#source-models option')).toHaveAttribute('value', 'current-suggestion');
    const late = page.waitForResponse((response) => response.url().includes(providers[0].id + '/models'));
    release();
    await (await late).finished();
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(dialog.locator('#source-models option')).toHaveAttribute('value', 'current-suggestion');
    await dialog.getByRole('button', { name: labels.close, exact: true }).click();
    const kind = page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true });
    for (const selected of ['embedding', 'tts', 'reranker', 'image_embedding', 'vision']) {
      await kind.selectOption(selected);
      await page.getByRole('button', { name: labels.addModel, exact: true }).click();
      await expect(source.locator('option[value="local"]')).toHaveCount(selected === 'tts' ? 1 : 0);
      const providerOptions = await source.locator('option[value^="provider:"]').count();
      expect(providerOptions > 0).toBe(selected === 'embedding');
      await expect(source).toHaveValue(selected === 'tts' ? 'local' : '');
      await dialog.getByRole('button', { name: labels.close, exact: true }).click();
    }
  });
}
