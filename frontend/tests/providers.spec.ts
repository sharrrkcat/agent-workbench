import { navigateModelSettings } from './controls';
import fs from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`Providers ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('direct toggles, busy and failed saves, independent key editing and local runtime', async ({ page, request }) => {
        await page.goto('/settings?tab=models&view=providers');
        const add = page.getByRole('button', { name: labels.addProvider, exact: true });
        const refresh = page.getByRole('button', { name: labels.refresh, exact: true });
        await add.click();
        const dialog = page.getByRole('dialog');
        const name = `External fixture ${locale} ${viewport.width}`;
        await expect(dialog.getByRole('switch')).toHaveCount(0);
        await dialog.getByLabel(labels.name, { exact: true }).fill(name);
        await dialog.getByLabel(labels.baseUrl, { exact: true }).fill('http://127.0.0.1:1234/v1');
        await dialog.getByLabel(labels.apiKey, { exact: true }).fill('fixture-secret');
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        let provider = (await (await request.get('/api/models/providers')).json()).find((item: { name: string }) => item.name === name);
        expect(provider.enabled).toBe(true);
        expect(provider.connection.has_api_key).toBe(true);
        expect(provider.connection).not.toHaveProperty('api_key');
        const card = page.getByRole('group', { name, exact: true });
        const toggle = card.getByRole('switch', { name: labels.providerEnabled.replace('{{name}}', name), exact: true });
        await expect(toggle).toBeChecked();
        const providerRoute = `**/api/models/providers/${provider.id}`;
        let release!: () => void;
        const gate = new Promise<void>((resolve) => { release = resolve; });
        await page.route(providerRoute, async (route) => {
          if (route.request().method() === 'PATCH') await gate;
          await route.continue();
        });
        const changed = page.waitForRequest((value) => value.method() === 'PATCH' && value.url().endsWith(`/providers/${provider.id}`));
        if (viewport.width === 390) {
          await toggle.scrollIntoViewIfNeeded();
          const box = (await toggle.boundingBox())!;
          await page.touchscreen.tap(box.x - 6, box.y + box.height / 2);
        } else {
          await toggle.focus();
          await toggle.press('Space');
        }
        expect((await changed).postDataJSON()).toEqual({ enabled: false });
        await expect(toggle).toBeDisabled();
        await expect(toggle).toBeChecked();
        await expect(add).toBeDisabled();
        await expect(refresh).toBeDisabled();
        await expect(card.getByRole('button', { name: labels.edit, exact: true })).toBeDisabled();
        await expect(card.getByRole('button', { name: labels.delete, exact: true })).toBeDisabled();
        release();
        await expect(toggle).not.toBeChecked();
        await expect(toggle).toBeEnabled();
        await page.unroute(providerRoute);

        await card.getByRole('button', { name: labels.edit, exact: true }).click();
        await expect(dialog.getByRole('switch')).toHaveCount(0);
        await expect(dialog.getByLabel(labels.apiKey, { exact: true })).toHaveValue('');
        await expect(dialog.getByLabel(labels.apiKey, { exact: true })).toHaveAttribute('placeholder', labels.keySet);
        await dialog.getByLabel(labels.connection.timeout_seconds, { exact: true }).fill('90');
        const preserved = page.waitForRequest((value) => value.method() === 'PATCH' && value.url().endsWith(`/providers/${provider.id}`));
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        const editPayload = (await preserved).postDataJSON();
        expect(editPayload).not.toHaveProperty('enabled');
        expect(editPayload.connection).not.toHaveProperty('api_key');
        await expect(dialog).toHaveCount(0);
        provider = await (await request.get(`/api/models/providers/${provider.id}`)).json();
        expect(provider.enabled).toBe(false);
        expect(provider.connection.has_api_key).toBe(true);
        expect(provider.connection.timeout_seconds).toBe(90);

        await page.route(providerRoute, (route) => route.fulfill({ status: 409, json: {
          error: { code: 'MODEL_BUSY', message: 'Fixture provider is busy' },
        } }), { times: 1 });
        await toggle.click();
        await expect(page.getByRole('alert')).toContainText('MODEL_BUSY: Fixture provider is busy');
        await expect(toggle).toBeEnabled();
        await expect(toggle).not.toBeChecked();
        await toggle.click();
        await expect(toggle).toBeChecked();
        await expect(page.getByRole('status')).toHaveText(labels.saved);
        await page.reload();
        await expect(toggle).toBeChecked();

        await card.getByRole('button', { name: labels.edit, exact: true }).click();
        await dialog.getByLabel(labels.apiKey, { exact: true }).fill('clear');
        await dialog.getByLabel(labels.apiKey, { exact: true }).fill('');
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        expect((await (await request.get(`/api/models/providers/${provider.id}`)).json()).connection.has_api_key).toBe(false);
        await card.getByRole('button', { name: labels.delete, exact: true }).click();
        await expect(card).toHaveCount(0);
        await navigateModelSettings(page, 'localRuntime');
        await expect(page.getByRole('group', { name: labels.coreRuntime, exact: true })).toBeVisible();
        await expect(page.locator('.runtime-panel').getByRole('switch')).toHaveCount(0);
      });

      test('full-width cards wrap long content and retain an empty-state toolbar', async ({ page }, info) => {
        const longName = (locale === 'en' ? 'LongProviderNameWithoutSpaces' : '很长的服务提供商名称').repeat(5);
        let providers = [longName, 'Local connection'].map((name, index) => ({
          id: `layout-${index}`, name, enabled: index === 0,
          connection: { base_url: `https://provider.test/${'long-endpoint-segment'.repeat(8)}/v1`, has_api_key: true },
        }));
        await page.route('**/api/models/providers', (route) => route.fulfill({ json: providers }));
        await page.goto('/settings?tab=models&view=providers');
        const cards = page.locator('.provider-card');
        await expect(cards).toHaveCount(2);
        await expect(page.locator('.model-heading')).toHaveCount(0);
        const toolbar = page.locator('.model-toolbar:visible');
        await expect(toolbar.getByRole('button', { name: labels.refresh, exact: true })).toHaveCount(1);
        await expect(toolbar.getByRole('button', { name: labels.addProvider, exact: true })).toHaveCount(1);
        const first = (await cards.nth(0).boundingBox())!, second = (await cards.nth(1).boundingBox())!;
        expect(second.x).toBe(first.x);
        expect(second.width).toBe(first.width);
        expect(second.y).toBeGreaterThan(first.y + first.height);
        expect(first.width).toBeCloseTo((await toolbar.boundingBox())!.width, 0);
        for (const [index, card] of (await cards.all()).entries()) {
          await expect(card).toHaveText(providers[index].name + providers[index].connection.base_url);
          await expect(card.locator('[data-slot="card-title"]')).toHaveCSS('font-size', '14px');
          await expect(card.locator('[data-slot="card-description"]')).toHaveCSS('font-size', '12px');
          const toggle = (await card.getByRole('switch').boundingBox())!;
          const title = (await card.locator('[data-slot="card-title"]').boundingBox())!;
          const actions = (await card.locator('[data-slot="card-action"]').boundingBox())!;
          expect(toggle.x + toggle.width).toBeLessThan(title.x);
          if (viewport.width === 390) {
            expect(actions.y).toBeGreaterThan(title.y + title.height);
            for (const button of await card.getByRole('button').all()) {
              const box = (await button.boundingBox())!;
              expect(box.width).toBeGreaterThanOrEqual(44);
              expect(box.height).toBeGreaterThanOrEqual(44);
            }
          } else expect(actions.x).toBeGreaterThan(title.x + title.width);
        }
        expect(await page.locator('.settings-content').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: info.outputPath('provider-cards.png'), animations: 'disabled' });
        providers = [];
        await toolbar.getByRole('button', { name: labels.refresh, exact: true }).click();
        await expect(cards).toHaveCount(0);
        await expect(page.getByText(labels.emptyProviders, { exact: true })).toBeVisible();
        await expect(toolbar.getByRole('button', { name: labels.addProvider, exact: true })).toBeEnabled();
      });
    });
  }
}
