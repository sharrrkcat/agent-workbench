import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import type { TextEmbeddingInspection } from '../src/types/models';
import { chooseOption, fillCombobox } from './controls';

const reference = 'embeddings/browser-text';
const information: TextEmbeddingInspection = {
  kind: 'embedding', model_ref: reference, model_type: 'example-backbone',
  modules: [{ name: '0', path: '', type: 'sentence_transformers.models.Transformer' },
    { name: '1', path: '1_Pooling', type: 'sentence_transformers.models.Pooling' },
    { name: '2', path: '2_Normalize', type: 'sentence_transformers.models.Normalize' }],
  pooling: [{ module: '1', modes: ['lasttoken'], include_prompt: true }],
  normalize: true, dimensions: 1024, max_seq_length: 32768, similarity: 'cosine',
  prompts: { web_search_query: 'Retrieve passages: ', sts_query: 'Find similar text: ' },
  query_prompt_name: 'web_search_query', document_prompt_name: null, diagnostics: [],
};

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`Text embedding ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test('directory configuration, prompt selection, source changes and saved drafts', async ({ page, request }, info) => {
        const provider = await (await request.post('/api/models/providers', { data: {
          name: `Embedding provider ${locale} ${viewport.width}`, connection: { base_url: 'http://127.0.0.1:1/v1' },
        } })).json();
        await page.route('**/api/models/inventory?kind=embedding', (route) => route.fulfill({ json: [
          { kind: 'embedding', name: 'browser-text', model_ref: reference, state: 'unavailable', error_code: 'MODEL_UNAVAILABLE' },
        ] }));
        await page.route('**/api/models/inspect?**', async (route) => {
          const query = new URL(route.request().url()).searchParams;
          if (query.get('kind') !== 'embedding') return route.continue();
          const modelRef = query.get('model_ref')!;
          const result: TextEmbeddingInspection = { ...information, model_ref: modelRef,
            query_prompt_name: query.get('query_prompt_name') ?? 'web_search_query' };
          if (modelRef.includes('incomplete')) result.diagnostics = [
            { file: '1_Pooling/config.json', code: 'missing_pooling', message: 'Pooling is missing.', blocking: true },
          ];
          await route.fulfill({ json: result });
        });
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/settings?tab=models');
        await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds.embedding);
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const input = dialog.getByLabel(labels.modelRef, { exact: true });
        await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
        await fillCombobox(input, reference);
        await expect(dialog.getByLabel(labels.name, { exact: true })).toHaveValue('browser-text');
        await expect(dialog).toContainText('1024');
        await expect(dialog).toContainText('32768');
        await expect(dialog).toContainText('lasttoken');
        await expect(dialog).toContainText('Retrieve passages:');
        await expect(dialog.getByLabel(labels.params.dimensions, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.params.normalize, { exact: true })).toHaveCount(0);
        await dialog.getByRole('button', { name: labels.textEmbedding.promptSettings, exact: true }).click();
        const prompts = dialog.locator('[data-slot="collapsible-content"]');
        await chooseOption(prompts.getByLabel(labels.textEmbedding.queryPrompt, { exact: true }), 'sts_query');
        await expect(dialog).toContainText('Find similar text:');
        const name = dialog.getByLabel(labels.name, { exact: true });
        await name.fill('Named embedding');
        await chooseOption(dialog.getByLabel(labels.runtimeDevice, { exact: true }), 'CPU');
        await dialog.getByLabel(labels.runtimeParams.max_batch_size, { exact: true }).fill('4');
        await fillCombobox(input, 'embeddings/incomplete');
        await expect(name).toHaveValue('Named embedding');
        await expect(dialog).toContainText(labels.textEmbedding.diagnostics.missing_pooling);
        await expect(dialog).toContainText(labels.textEmbedding.draftHint);
        const alias = `text-embedding-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        if (viewport.width === 390) expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBeTruthy();
        await page.screenshot({ path: info.outputPath('text-embedding-editor.png') });
        await save.click();
        await expect(dialog).toHaveCount(0);
        const saved = (await (await request.get('/api/models/profiles')).json()).find((item: { alias: string }) => item.alias === alias);
        expect(saved.source.execution_options).toEqual({ device: 'cpu', intraop_threads: 4, max_batch_size: 4 });
        expect(saved.parameters).toEqual({ query_prompt_name: null, document_prompt_name: null });
        const row = page.locator('.model-list .model-row').filter({ hasText: alias });
        await row.getByRole('button', { name: labels.edit, exact: true }).click();
        await chooseOption(source, provider.name);
        await expect(input).toHaveValue('');
        await expect(dialog.getByText(labels.textEmbedding.information, { exact: true })).toHaveCount(0);
        await expect(dialog.getByLabel(labels.params.dimensions, { exact: true })).toBeVisible();
        await expect(source).toBeVisible();
        await chooseOption(source, labels.localRuntime);
        await fillCombobox(input, reference);
        await expect(dialog).toContainText('Retrieve passages:');
        await expect(name).toHaveValue('Named embedding');
        await save.click();
        await expect(dialog).toHaveCount(0);
        const updated = await (await request.get(`/api/models/profiles/${saved.id}`)).json();
        expect(updated.source.execution_options.device).toBe('cuda');
        expect(updated.parameters).toEqual({ query_prompt_name: null, document_prompt_name: null });
      });
    });
  }
}
