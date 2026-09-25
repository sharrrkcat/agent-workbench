import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const actual = createModuleLoader();
const { default: i18n } = (await actual('../src/i18n/index.ts')).exports;
const calls = [];
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(i18n.language, namespace) }) }),
  [sourceUrl('api/http.ts')]: mockModule({ request: async (...args) => { calls.push(args); return {}; } }),
});
const { newModel, localEngine, localSource, selectModelSource, selectModelReference } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const { TextEmbeddingInspectionPanel } = (await load('../src/components/settings/models/TextEmbeddingInspection.tsx')).exports;
const { modelsApi } = (await load('../src/api/models.ts')).exports;

const model = newModel('embedding');
assert.equal(localEngine(model), 'sentence-transformers');
assert.deepEqual(model.parameters, { query_prompt_name: null, document_prompt_name: null });
assert.deepEqual(model.source.execution_options, { device: 'cuda', intraop_threads: 4, max_batch_size: 1 });
assert.equal(model.source.lifecycle.unload, 'manual');
const selected = selectModelReference(model, 'embeddings/model-a', true);
assert.equal(selected.name, 'model-a');
const edited = { ...selected, name: 'My embedding', parameters: { query_prompt_name: 'sts_query', document_prompt_name: null },
  source: { ...selected.source, execution_options: { device: 'cpu', intraop_threads: 2, max_batch_size: 4 } } };
const changed = selectModelReference(edited, 'embeddings/model-b', true);
assert.equal(changed.name, edited.name);
assert.deepEqual(changed.parameters, model.parameters);
assert.deepEqual(changed.source, edited.source);
assert.equal(selectModelSource(edited, localSource()), edited);
const provider = selectModelSource(edited, { type: 'provider', provider_profile_id: 'provider-id' });
assert.deepEqual(provider.parameters, {});
assert.equal(provider.model_ref, '');
assert.equal(localEngine(provider), null);
const local = selectModelSource(provider, localSource());
assert.deepEqual(local.parameters, model.parameters);
assert.equal(localEngine(local), 'sentence-transformers');
assert.equal(selectModelSource(edited, null).model_ref, edited.model_ref);

for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  assert.equal(ProfileParameters({ value: model, onChange() {} }), null);
  const markup = renderToStaticMarkup(React.createElement(TextEmbeddingInspectionPanel, {
    modelRef: selected.model_ref, parameters: model.parameters, onChange() {},
  }));
  assert.ok(markup.includes(i18n.t('textEmbedding.information', { ns: 'llm' })));
  assert.ok(markup.includes(i18n.t('textEmbedding.inspecting', { ns: 'llm' })));
}
await modelsApi.inspectTextEmbedding('embeddings/模型', { query_prompt_name: 'web_search_query', document_prompt_name: null });
const query = new URL(calls.at(-1)[0], 'http://test').searchParams;
assert.equal(query.get('kind'), 'embedding');
assert.equal(query.get('model_ref'), 'embeddings/模型');
assert.equal(query.get('query_prompt_name'), 'web_search_query');
assert.equal(query.has('document_prompt_name'), false);
console.log('Local text embedding defaults, source resets, read-only parameters, locales and inspection requests passed.');
