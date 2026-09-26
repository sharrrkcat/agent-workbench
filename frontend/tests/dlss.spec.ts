import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { chooseOption, fillCombobox } from './controls';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`DLSS ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test('processor controls round-trip and component tasks stay separate', async ({ page, request }, info) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/settings?tab=models');
        await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds.processor);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        await fillCombobox(dialog.getByLabel(labels.modelRef, { exact: true }), 'processors/dlss5-nr');
        await expect(dialog).toContainText('nvngx_dlssnr.dll');
        await expect(dialog.getByLabel(labels.runtimeDevice, { exact: true })).toContainText('NVIDIA D3D12');
        await expect(dialog.getByLabel(labels.runtimeDevice, { exact: true })).toBeDisabled();
        await dialog.getByLabel(labels.processor.intensity, { exact: true }).fill('0');
        await dialog.getByRole('group', { name: labels.processor.style, exact: true }).getByRole('button', { name: labels.processor.styles.cinematic, exact: true }).click();
        await dialog.getByRole('group', { name: labels.processor.preset, exact: true }).getByRole('button', { name: '0', exact: true }).click();
        await dialog.getByLabel(labels.runtimeParams.gpu_index, { exact: true }).fill('1');
        const alias = `dlss-${locale.toLowerCase()}-${width}`;
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBeTruthy();
        await page.screenshot({ path: info.outputPath('processor-controls.png') });
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        const saved = (await (await request.get('/api/models/profiles')).json()).find((item: { alias: string }) => item.alias === alias);
        expect(saved.parameters).toMatchObject({ task: 'image_processing', intensity: 0, preset: 0, style: 'cinematic', auto_mask: false });
        expect(saved.source.execution_options).toEqual({ device: 'd3d12', gpu_index: 1 });
        expect(saved.external_enabled).toBe(false);
        await page.locator('.model-list .model-row').filter({ hasText: alias }).getByRole('button', { name: labels.edit, exact: true }).click();
        await expect(dialog.getByLabel(labels.processor.intensity, { exact: true })).toHaveValue('0');
        await page.keyboard.press('Escape');
        await expect(dialog).toHaveCount(0);
        await page.route('**/api/models/local-runtime/jobs', (route) => route.fulfill({ json: [
          { id: 'component-job', component_id: 'dlss5nr', version: '0.1.0', operation: 'repair', state: 'running', stage: 'checking_component', revision: 2, created_at: '2026-09-26T00:00:01Z', cancel_requested: false },
          { id: 'base-job', component_id: null, version: '1.0.0', operation: 'install', state: 'completed', stage: 'completed', revision: 1, created_at: '2026-09-26T00:00:00Z' },
        ] }));
        await page.goto('/settings?tab=models&view=localRuntime');
        const base = page.getByRole('group', { name: labels.localInstallation, exact: true });
        const component = page.getByRole('group', { name: labels.dlssComponent, exact: true });
        await expect(base).toContainText(labels.runtimeStages.completed);
        await expect(base).not.toContainText(labels.runtimeStages.checking_component);
        await expect(component).toContainText(labels.runtimeStages.checking_component);
        await expect(component.getByRole('button', { name: labels.cancelTask, exact: true })).toBeEnabled();
        await page.screenshot({ path: info.outputPath('component-installation.png') });
      });
    });
  }
}
