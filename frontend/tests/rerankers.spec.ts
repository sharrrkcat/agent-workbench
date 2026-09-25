import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import type { RerankerInspection } from '../src/types/models';
import { chooseOption, fillCombobox } from './controls';

const reference = 'rerankers/browser-model';
const information: RerankerInspection = {
  kind: 'reranker', model_ref: reference, architecture: 'cross-encoder', model_type: 'example-backbone',
  modules: [{ name: '0', path: '', type: 'sentence_transformers.base.modules.transformer.Transformer' },
    { name: '1', path: '1_Score', type: 'sentence_transformers.cross_encoder.modules.logit_score.LogitScore' }],
  scoring: { method: 'logit_score', activation: 'torch.nn.Sigmoid' }, max_seq_length: 32768,
  has_chat_template: true, default_prompt_name: null, diagnostics: [],
};

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`Reranker ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test('automatic configuration, stale responses and invalid directory drafts', async ({ page, request }, info) => {
        let releaseSlow: (() => void) | undefined;
        await page.route('**/api/models/inventory?kind=reranker', (route) => route.fulfill({ json: [
          { kind: 'reranker', name: 'browser-model', model_ref: reference, mmproj_refs: [], state: 'unavailable', error_code: 'MODEL_UNAVAILABLE' },
        ] }));
        await page.route('**/api/models/inspect?**', async (route) => {
          const query = new URL(route.request().url()).searchParams;
          if (query.get('kind') !== 'reranker') return route.continue();
          const modelRef = query.get('model_ref')!;
          if (modelRef === 'rerankers/slow') await new Promise<void>((resolve) => { releaseSlow = resolve; });
          const result: RerankerInspection = { ...information, model_ref: modelRef };
          if (modelRef === 'rerankers/slow') result.model_type = 'stale-backbone';
          if (modelRef === 'rerankers/incomplete') {
            result.model_type = 'incomplete-backbone';
            result.scoring = { method: null, activation: null };
            result.diagnostics = [{ file: 'modules.json', code: 'missing_scoring', message: 'Scoring is missing.', blocking: true }];
          }
          await route.fulfill({ json: result });
        });
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/settings?tab=models');
        await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds.reranker);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const input = dialog.getByLabel(labels.modelRef, { exact: true });
        const name = dialog.getByLabel(labels.name, { exact: true });
        await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
        await fillCombobox(input, reference);
        await expect(name).toHaveValue('browser-model');
        await expect(dialog).toContainText('example-backbone');
        await expect(dialog).toContainText('32768');
        await expect(dialog).toContainText('Transformer → LogitScore');
        await expect(dialog).toContainText('Sigmoid');
        await expect(dialog.getByLabel(labels.reranker.fields.architecture, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.params.batch_size, { exact: true })).toHaveCount(0);
        await expect(dialog.getByRole('heading', { name: labels.parameters, exact: true })).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('reranker-editor.png') });
        await name.fill('Named reranker');
        await chooseOption(dialog.getByLabel(labels.runtimeDevice, { exact: true }), 'CPU');
        await dialog.getByLabel(labels.runtimeParams.max_batch_size, { exact: true }).fill('4');
        const slowResponse = page.waitForResponse((response) => response.url().includes('/api/models/inspect?')
          && new URL(response.url()).searchParams.get('model_ref') === 'rerankers/slow');
        await fillCombobox(input, 'rerankers/slow');
        await expect.poll(() => Boolean(releaseSlow)).toBeTruthy();
        await expect(dialog).toContainText(labels.reranker.inspecting);
        await expect(dialog.getByText('example-backbone', { exact: true })).toHaveCount(0);
        await fillCombobox(input, 'rerankers/incomplete');
        await expect(dialog).toContainText(labels.reranker.diagnostics.missing_scoring);
        releaseSlow!();
        await slowResponse;
        await expect(dialog).toContainText('incomplete-backbone');
        await expect(dialog.getByText('stale-backbone', { exact: true })).toHaveCount(0);
        await expect(name).toHaveValue('Named reranker');
        await expect(dialog).toContainText(labels.reranker.draftHint);
        const alias = `reranker-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBeTruthy();
        if (viewport.width === 390) expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await save.click();
        await expect(dialog).toHaveCount(0);
        const saved = (await (await request.get('/api/models/profiles')).json()).find((item: { alias: string }) => item.alias === alias);
        expect(saved.source.execution_options).toEqual({ device: 'cpu', intraop_threads: 4, max_batch_size: 4 });
        expect(saved.source.lifecycle.unload).toBe('manual');
        expect(saved.parameters).toEqual({});
        await page.locator('.model-list .model-row').filter({ hasText: alias }).getByRole('button', { name: labels.edit, exact: true }).click();
        await chooseOption(source, labels.unbound);
        await expect(input).toHaveValue('rerankers/incomplete');
        await expect(dialog.getByText(labels.reranker.information, { exact: true })).toHaveCount(0);
        await chooseOption(source, labels.localRuntime);
        await fillCombobox(input, reference);
        await expect(dialog).toContainText('example-backbone');
        await expect(name).toHaveValue('Named reranker');
        await save.click();
        await expect(dialog).toHaveCount(0);
      });
    });
  }
}
