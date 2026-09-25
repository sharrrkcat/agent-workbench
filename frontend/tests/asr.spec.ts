import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import type { ASRInspection } from '../src/types/models';
import { chooseOption, fillCombobox } from './controls';

const reference = 'asr/browser-model';
const information: ASRInspection = {
  kind: 'asr', model_ref: reference, architecture: 'whisper', processor: 'WhisperProcessor',
  sample_rate: 16000, feature_size: 128, window_seconds: 30, multilingual: true,
  languages: ['en', 'zh'], segment_timestamps: true, diagnostics: [],
};

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`ASR ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test('directory information, editable defaults and draft persistence', async ({ page, request }, info) => {
        let releaseSlow: (() => void) | undefined;
        await page.route('**/api/models/inventory?kind=asr', (route) => route.fulfill({ json: [
          { kind: 'asr', name: 'browser-model', model_ref: reference, mmproj_refs: [], state: 'unavailable', error_code: 'MODEL_UNAVAILABLE' },
        ] }));
        await page.route('**/api/models/inspect?**', async (route) => {
          const query = new URL(route.request().url()).searchParams;
          if (query.get('kind') !== 'asr') return route.continue();
          const modelRef = query.get('model_ref')!;
          if (modelRef === 'asr/slow') await new Promise<void>((resolve) => { releaseSlow = resolve; });
          const result: ASRInspection = { ...information, model_ref: modelRef };
          if (modelRef === 'asr/slow') result.processor = 'stale-processor';
          if (modelRef === 'asr/incomplete') {
            result.processor = null;
            result.diagnostics = [{ file: 'generation_config.json', code: 'missing_config', message: 'Missing config', blocking: true }];
          }
          await route.fulfill({ json: result });
        });
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/settings?tab=models');
        await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds.asr);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const input = dialog.getByLabel(labels.modelRef, { exact: true });
        await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
        await fillCombobox(input, reference);
        await expect(dialog.getByLabel(labels.name, { exact: true })).toHaveValue('browser-model');
        await expect(dialog).toContainText('WhisperProcessor');
        await expect(dialog).toContainText('16000');
        await expect(dialog).toContainText('en, zh');
        await expect(dialog.getByLabel(labels.asr.fields.architecture, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.asr.language, { exact: true })).toHaveValue('auto');
        await expect(dialog.getByLabel(labels.params.temperature, { exact: true })).toHaveValue('0');
        await expect(dialog.getByRole('switch', { name: labels.externalModel, exact: true })).not.toBeChecked();
        await expect(dialog).toContainText(labels.asr.timestampsHint);
        await dialog.getByLabel(labels.asr.language, { exact: true }).fill('zh');
        await dialog.getByLabel(labels.asr.prompt, { exact: true }).fill('示例 context');
        await dialog.getByLabel(labels.params.temperature, { exact: true }).fill('0.3');
        await chooseOption(dialog.getByLabel(labels.asr.responseFormat, { exact: true }), labels.asr.formats.verbose_json);
        await expect(page.getByRole('listbox')).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('asr-controls.png') });
        const slowResponse = page.waitForResponse((response) => response.url().includes('/api/models/inspect?')
          && new URL(response.url()).searchParams.get('model_ref') === 'asr/slow');
        await fillCombobox(input, 'asr/slow');
        await expect.poll(() => Boolean(releaseSlow)).toBeTruthy();
        await fillCombobox(input, 'asr/incomplete');
        await expect(dialog).toContainText(labels.asr.diagnostics.missing_config);
        releaseSlow!();
        await slowResponse;
        await expect(dialog.getByText('stale-processor', { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.name, { exact: true })).toHaveValue('browser-model');
        const alias = `asr-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBeTruthy();
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        if (viewport.width === 390) expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await save.click();
        await expect(dialog).toHaveCount(0);
        const saved = (await (await request.get('/api/models/profiles')).json()).find((item: { alias: string }) => item.alias === alias);
        expect(saved.parameters).toEqual({ language: 'zh', prompt: '示例 context', temperature: 0.3, response_format: 'verbose_json' });
        expect(saved.source.execution_options).toEqual({ device: 'cuda', intraop_threads: 4 });
        expect(saved.source.lifecycle.unload).toBe('manual');
        await page.locator('.model-list .model-row').filter({ hasText: alias }).getByRole('button', { name: labels.edit, exact: true }).click();
        await chooseOption(source, labels.unbound);
        await expect(input).toHaveValue('asr/incomplete');
        await expect(dialog.getByText(labels.asr.information, { exact: true })).toHaveCount(0);
        await dialog.getByLabel(labels.asr.language, { exact: true }).fill('auto');
        await dialog.getByLabel(labels.asr.prompt, { exact: true }).fill('');
        await chooseOption(dialog.getByLabel(labels.asr.responseFormat, { exact: true }), labels.asr.formats.text);
        await save.click();
        await expect(dialog).toHaveCount(0);
        const reset = await (await request.get(`/api/models/profiles/${saved.id}`)).json();
        expect(reset.parameters).toEqual({ language: 'auto', prompt: '', temperature: 0.3, response_format: 'text' });
        expect(reset.source).toBeNull();
      });
    });
  }
}
