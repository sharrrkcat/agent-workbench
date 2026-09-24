import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import type { ModelStatus } from '../src/types/models';
import { chooseOption, fillCombobox } from './controls';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`WD14 ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test('local inventory, thresholds, save and lifecycle controls', async ({ page, request }, info) => {
        expect((await request.post('/__test__/runtimes', { data: { wd14: true } })).ok()).toBeTruthy();
        await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await page.goto('/settings?tab=models');
        await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds.vision);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        const general = dialog.getByLabel(labels.tagThresholds.general, { exact: true });
        const character = dialog.getByLabel(labels.tagThresholds.character, { exact: true });
        const release = dialog.getByLabel(labels.release, { exact: true });
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
        await source.click();
        await expect(page.getByRole('option')).toHaveText([labels.unbound, labels.localRuntime]);
        await page.keyboard.press('Escape');
        await reference.press('ArrowDown');
        await expect(page.getByRole('option', { name: 'vision/browser-wd14', exact: true })).toBeVisible();
        await page.getByRole('option', { name: 'vision/browser-wd14', exact: true }).click();
        await expect(reference).toHaveValue('vision/browser-wd14');
        await fillCombobox(reference, 'vision/manual-family');
        await chooseOption(source, labels.unbound);
        await expect(reference).toHaveValue('vision/manual-family');
        await expect(general).toHaveValue('0.35');
        await chooseOption(source, labels.localRuntime);
        await expect(reference).toHaveValue('vision/manual-family');
        await fillCombobox(reference, 'vision/browser-wd14');
        const device = dialog.getByLabel(labels.runtimeDevice, { exact: true });
        await expect(device).toBeDisabled();
        await expect(device.locator('[data-slot="select-value"]')).toHaveText('CPU');
        await expect(dialog.getByLabel(labels.runtimeParams.intraop_threads, { exact: true })).toHaveValue('4');
        await expect(release.locator('[data-slot="select-value"]')).toHaveText(labels.policy.manual);
        await expect(dialog.getByLabel(labels.params.architecture, { exact: true })).toHaveValue('WD14');
        await expect(dialog.getByLabel(labels.params.task, { exact: true })).toHaveValue(labels.visionTags);
        await expect(dialog.getByLabel(labels.params.batch_size, { exact: true })).toHaveCount(0);
        await expect(dialog).toContainText(labels.visionDirectoryHint);
        await expect(character).toHaveValue('0.85');
        const alias = `runtime-fixture-wd14-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(labels.name, { exact: true }).fill('WD14 family');
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        await dialog.getByRole('switch', { name: labels.externalModel, exact: true }).click();
        await expect(dialog.getByRole('switch', { name: labels.externalModel, exact: true })).toBeChecked();
        await general.fill('');
        await save.click();
        await expect(dialog).toBeVisible();
        expect(await general.evaluate((node: HTMLInputElement) => node.validity.valueMissing)).toBe(true);
        await general.fill('1.01');
        expect(await general.evaluate((node: HTMLInputElement) => node.validity.rangeOverflow)).toBe(true);
        await general.fill('0');
        await character.fill('0.875');
        await chooseOption(release, labels.policy.idle);
        await dialog.getByLabel(labels.idleSeconds, { exact: true }).fill('90');
        await character.scrollIntoViewIfNeeded();
        expect(await page.evaluate(() => [...document.querySelectorAll('body, [data-slot="dialog-content"], [data-slot="field-group"]')]
          .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => node.className || node.tagName))).toEqual([]);
        const bounds = await dialog.boundingBox();
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
        if (viewport.width === 390) {
          expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(44);
          expect((await general.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        }
        await page.screenshot({ path: info.outputPath('wd14-thresholds.png') });
        await save.click();
        await expect(dialog).toHaveCount(0);
        const profiles = await (await request.get('/api/models/profiles')).json();
        const saved = profiles.find((item: { alias: string }) => item.alias === alias);
        expect(saved.parameters).toEqual({ architecture: 'wd14', task: 'tags', thresholds: { general: 0, character: 0.875 } });
        expect(saved.source.execution_options).toEqual({ device: 'cpu', intraop_threads: 4, max_batch_size: 1 });
        expect(saved.source.lifecycle).toEqual({ unload: 'idle', idle_seconds: 90 });
        expect(saved.external_enabled).toBe(true);
        const row = page.locator('.model-list .model-row').filter({ hasText: alias });
        await row.getByRole('button', { name: labels.edit, exact: true }).click();
        await expect(general).toHaveValue('0');
        await expect(character).toHaveValue('0.875');
        await expect(release.locator('[data-slot="select-value"]')).toHaveText(labels.policy.idle);
        await chooseOption(release, labels.policy.after_request);
        await save.click();
        await expect(dialog).toHaveCount(0);
        expect((await (await request.get(`/api/models/profiles/${saved.id}`)).json()).source.lifecycle.unload).toBe('after_request');

        // UI state/actions use deterministic responses; real workers are covered by smoke acceptance.
        let status: ModelStatus = { state: 'unloaded', residency: 'unloaded', unload_supported: true, active: 0,
          queued: 0, error_code: null, runtime: { engine: 'wd14', version: '1.0.0', install_state: 'installed',
            process_state: 'stopped', job_id: null, device_name: 'CPU', gpu_layers_loaded: null, gpu_layers_total: null } };
        const actions: string[] = [];
        let finishLoad!: () => void;
        const pending = new Promise<void>((resolve) => { finishLoad = resolve; });
        await page.route(`**/api/models/profiles/${saved.id}/*`, async (route) => {
          const action = route.request().url().split('/').pop()!;
          if (action === 'log') return route.fulfill({ json: { text: 'WD14 CPU worker ready' } });
          if (['load', 'unload', 'health'].includes(action)) {
            actions.push(action);
            if (action === 'load') await pending;
            const loaded = action === 'load';
            status = { ...status, state: loaded ? 'ready' : 'unloaded', residency: loaded ? 'loaded' : 'unloaded',
              runtime: { ...status.runtime!, process_state: loaded ? 'ready' : 'stopped' } };
          }
          return route.fulfill({ json: status });
        });
        await row.getByRole('button', { name: labels.health, exact: true }).click();
        await expect(row).toContainText(labels.states.unloaded);
        await row.getByRole('button', { name: labels.load, exact: true }).click();
        await expect.poll(() => actions.includes('load')).toBe(true);
        await expect(row.getByRole('button', { name: labels.edit, exact: true })).toBeDisabled();
        finishLoad();
        await expect(row).toContainText(labels.states.ready);
        await expect(row).toContainText(labels.engines.wd14);
        await row.getByRole('button', { name: labels.processLog, exact: true }).click();
        await expect(dialog).toContainText('WD14 CPU worker ready');
        await dialog.getByRole('button', { name: labels.close, exact: true }).click();
        await row.getByRole('button', { name: labels.unload, exact: true }).click();
        await expect(row).toContainText(labels.states.unloaded);
        expect(actions).toEqual(['health', 'load', 'unload']);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
        await page.screenshot({ path: info.outputPath('wd14-status.png') });
        expect(errors).toEqual([]);
      });
    });
  }
}
