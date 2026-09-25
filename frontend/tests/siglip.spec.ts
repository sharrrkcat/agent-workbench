import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import type { ModelStatus, SiglipInspection, SiglipTower } from '../src/types/models';
import { chooseOption, fillCombobox } from './controls';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`SigLIP ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test('inspection, drafts, switch, execution options and tower actions', async ({ page, request }, info) => {
        expect((await request.post('/__test__/runtimes', { data: { siglip2: true } })).ok()).toBeTruthy();
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await page.goto('/settings?tab=models');
        await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds.image_embedding);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        const name = dialog.getByLabel(labels.name, { exact: true });
        const autoUnload = dialog.getByRole('switch', { name: labels.siglip.unloadOther, exact: true });
        const device = dialog.getByLabel(labels.runtimeDevice, { exact: true });
        const batch = dialog.getByLabel(labels.runtimeParams.max_batch_size, { exact: true });
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
        await expect(source).toBeDisabled();
        await expect(autoUnload).toBeChecked();
        await expect(device.locator('[data-slot="select-value"]')).toHaveText('NVIDIA CUDA');
        await expect(batch).toHaveValue('1');
        await reference.press('ArrowDown');
        await page.getByRole('option', { name: 'image_embeddings/browser-naflex', exact: true }).click();
        await expect(name).toHaveValue('browser-naflex');
        await expect(dialog).toContainText(labels.siglip.structures.naflex);
        await expect(dialog.getByText(labels.siglip.fields.textLimit, { exact: true }).locator('..')).toContainText('64');
        await expect(dialog).not.toContainText('1e+30');
        await expect(dialog.getByLabel(labels.directory.fields.architecture, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.params.dimensions, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.params.batch_size, { exact: true })).toHaveCount(0);
        await name.fill('My model');
        await autoUnload.click();
        await batch.fill('4');
        await chooseOption(device, 'CPU');
        let finishInspection!: () => void;
        const pending = new Promise<void>((resolve) => { finishInspection = resolve; });
        let delayedStarted = false;
        await page.route('**/api/models/inspect?**', async (route) => {
          const modelRef = new URL(route.request().url()).searchParams.get('model_ref');
          if (modelRef !== 'image_embeddings/delayed') return route.continue();
          const value = await (await request.get('/api/models/inspect?kind=image_embedding&model_ref=image_embeddings/browser-naflex')).json() as SiglipInspection;
          delayedStarted = true;
          await pending;
          await route.fulfill({ json: { ...value, model_ref: modelRef, image: { ...value.image, dimensions: 999 } } });
        });
        await fillCombobox(reference, 'image_embeddings/delayed');
        await expect.poll(() => delayedStarted).toBe(true);
        await expect(dialog).toContainText(labels.siglip.inspecting);
        await expect(dialog).not.toContainText(labels.siglip.structures.naflex);
        await fillCombobox(reference, 'image_embeddings/browser-fixres');
        await expect(dialog).toContainText(labels.siglip.structures.fixres);
        finishInspection();
        await expect(dialog).toContainText(labels.siglip.fixresHint);
        await expect(dialog).not.toContainText('999');
        await expect(name).toHaveValue('My model');
        await expect(autoUnload).not.toBeChecked();
        await expect(batch).toHaveValue('4');
        await expect(device.locator('[data-slot="select-value"]')).toHaveText('CPU');
        await fillCombobox(reference, 'image_embeddings/incomplete');
        await expect(dialog).toContainText(labels.siglip.diagnostics.missing_config);
        await expect(dialog).toContainText(labels.siglip.pending);
        await fillCombobox(reference, 'image_embeddings/missing');
        await expect(dialog).toContainText(labels.siglip.inspectionFailed);
        const alias = `runtime-fixture-siglip-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        await save.click();
        await expect(dialog).toHaveCount(0);
        const profiles = await (await request.get('/api/models/profiles')).json();
        const saved = profiles.find((item: { alias: string }) => item.alias === alias);
        expect(saved.parameters).toEqual({ unload_other_tower_on_call: false });
        expect(saved.source.execution_options).toEqual({ device: 'cpu', intraop_threads: 4, max_batch_size: 4 });
        const row = page.locator('.model-list .model-row').filter({ hasText: alias });
        await row.getByRole('button', { name: labels.edit, exact: true }).click();
        await expect(name).toHaveValue('My model');
        await expect(autoUnload).not.toBeChecked();
        await expect(source).toBeDisabled();
        await expect(reference).toHaveValue('image_embeddings/missing');
        await expect(dialog.getByText(labels.siglip.information, { exact: true })).toBeVisible();
        await fillCombobox(reference, 'image_embeddings/browser-naflex');
        await expect(name).toHaveValue('My model');
        await expect(autoUnload).not.toBeChecked();
        await chooseOption(device, 'NVIDIA CUDA');
        await batch.fill('8');
        await chooseOption(dialog.getByLabel(labels.release, { exact: true }), labels.policy.idle);
        await dialog.getByLabel(labels.idleSeconds, { exact: true }).fill('90');
        await batch.scrollIntoViewIfNeeded();
        expect(await page.evaluate(() => [...document.querySelectorAll('body, [data-slot="dialog-content"], [data-slot="field-group"]')]
          .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => node.tagName))).toEqual([]);
        if (viewport.width === 390) expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await page.screenshot({ path: info.outputPath('siglip-editor.png') });
        await save.click();
        await expect(dialog).toHaveCount(0);
        const updated = await (await request.get(`/api/models/profiles/${saved.id}`)).json();
        expect(updated.source.execution_options.max_batch_size).toBe(8);
        expect(updated.source.lifecycle).toEqual({ unload: 'idle', idle_seconds: 90 });

        const stopped = { process_state: 'stopped' as const, residency: 'unloaded' as const, error_code: null, info: null };
        let status: ModelStatus = { state: 'unloaded', residency: 'unloaded', unload_supported: true, active: 0, queued: 0, error_code: null,
          towers: { image: stopped, text: stopped, active_tower: null, dimensions: null, model_revision: null, vector_space_id: null },
          runtime: { engine: 'siglip2', version: '1.0.0', install_state: 'installed', process_state: 'stopped', job_id: null,
            device_name: null, gpu_layers_loaded: null, gpu_layers_total: null } };
        const actions: string[] = [];
        await page.route(`**/api/models/profiles/${saved.id}/*`, async (route) => {
          const url = new URL(route.request().url());
          const action = url.pathname.split('/').pop()!;
          if (action === 'log') {
            actions.push('log:' + url.searchParams.get('tower'));
            return route.fulfill({ json: { text: `${url.searchParams.get('tower')} worker ready` } });
          }
          if (action === 'load') {
            const tower = route.request().postDataJSON().tower as SiglipTower;
            actions.push('load:' + tower);
            status = { ...status, state: 'ready', residency: 'loaded',
              runtime: { ...status.runtime!, process_state: 'ready', device_name: 'Fixture CUDA' },
              towers: { ...status.towers!, [tower]: { ...stopped, process_state: 'ready', residency: 'loaded' },
                dimensions: 768, model_revision: 'sha256:' + 'a'.repeat(64), vector_space_id: 'sha256:' + 'b'.repeat(64) } };
          } else if (action === 'unload') {
            actions.push(action);
            status = { ...status, state: 'unloaded', residency: 'unloaded', towers: { ...status.towers!, image: stopped, text: stopped,
              model_revision: null, vector_space_id: null, dimensions: null } };
          }
          return route.fulfill({ json: status });
        });
        for (const tower of ['image', 'text']) {
          await row.getByRole('button', { name: labels.load, exact: true }).click();
          const item = page.getByRole('menuitem', { name: labels.siglip.load[tower], exact: true });
          if (viewport.width === 390) await expect.poll(async () => (await item.boundingBox())!.height).toBeGreaterThanOrEqual(44);
          await item.click();
          await expect(row).toContainText(`${labels.siglip.tower[tower]}: ${labels.siglip.states.ready}`);
          await row.getByRole('button', { name: labels.processLog, exact: true }).click();
          await page.getByRole('menuitem', { name: labels.siglip.log[tower], exact: true }).click();
          await expect(dialog).toContainText(`${tower} worker ready`);
          await expect(dialog.getByRole('heading')).toHaveText(labels.siglip.log[tower]);
          await dialog.getByRole('button', { name: labels.close, exact: true }).click();
          await expect(dialog).toHaveCount(0);
        }
        await expect(row).toContainText(labels.siglip.revision);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
        await page.screenshot({ path: info.outputPath('siglip-status.png') });
        await row.getByRole('button', { name: labels.unload, exact: true }).click();
        await expect(row).not.toContainText('sha256:');
        expect(actions).toEqual(['load:image', 'log:image', 'load:text', 'log:text', 'unload']);
        expect(errors).toEqual([]);
      });
    });
  }
}
