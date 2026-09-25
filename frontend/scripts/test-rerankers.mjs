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
const { RerankerInspectionPanel } = (await load('../src/components/settings/models/RerankerInspection.tsx')).exports;
const { modelsApi } = (await load('../src/api/models.ts')).exports;

const model = newModel('reranker');
assert.equal(localEngine(model), 'cross-encoder');
assert.deepEqual(model.parameters, {});
assert.deepEqual(model.source.execution_options, { device: 'cuda', intraop_threads: 4, max_batch_size: 1 });
assert.equal(model.source.lifecycle.unload, 'manual');
const selected = selectModelReference(model, 'rerankers/model-a', true);
assert.equal(selected.name, 'model-a');
const edited = { ...selected, name: 'My reranker', source: {
  ...selected.source, execution_options: { device: 'cpu', intraop_threads: 2, max_batch_size: 4 },
} };
const changed = selectModelReference(edited, 'rerankers/model-b', true);
assert.equal(changed.name, edited.name);
assert.deepEqual(changed.source, edited.source);
assert.deepEqual(changed.parameters, {});
assert.equal(selectModelSource(edited, localSource()), edited);
const unbound = selectModelSource(edited, null);
assert.equal(unbound.model_ref, edited.model_ref);
assert.equal(localEngine(unbound), null);
assert.equal(localEngine(selectModelSource(unbound, localSource())), 'cross-encoder');

for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  assert.equal(ProfileParameters({ value: model, onChange() {} }), null);
  assert.equal(ProfileParameters({ value: unbound, onChange() {} }), null);
  const markup = renderToStaticMarkup(React.createElement(RerankerInspectionPanel, { modelRef: selected.model_ref }));
  assert.ok(markup.includes(i18n.t('reranker.information', { ns: 'llm' })));
  assert.ok(markup.includes(i18n.t('reranker.inspecting', { ns: 'llm' })));
}
await modelsApi.inspectReranker('rerankers/模型');
const query = new URL(calls.at(-1)[0], 'http://test').searchParams;
assert.deepEqual([...query], [['kind', 'reranker'], ['model_ref', 'rerankers/模型']]);
console.log('Reranker defaults, directory selection, runtime settings, locales and inspection requests passed.');
