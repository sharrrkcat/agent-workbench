import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const i18n = i18next.createInstance();
await i18n.init({ lng: 'en', interpolation: { escapeValue: false }, resources:
  Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale, {
    llm: JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8')),
  }])) });
const calls = [];
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
  [sourceUrl('api/http.ts')]: mockModule({ request: async (...args) => { calls.push(args); return {}; } }),
});
const { newModel, localEngine, localSource, selectModelSource, selectModelReference } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const { SiglipInspectionPanel } = (await load('../src/components/settings/models/SiglipInspection.tsx')).exports;
const { Switch } = (await load('../src/components/ui/switch.tsx')).exports;
const { modelsApi } = (await load('../src/api/models.ts')).exports;
function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!React.isValidElement(node)) return [];
  return [node, ...descendants(node.props.children)];
}
const model = newModel('image_embedding');
assert.equal(localEngine(model), 'siglip2');
assert.deepEqual(model.parameters, { unload_other_tower_on_call: true });
assert.deepEqual(model.source.execution_options, { device: 'cuda', intraop_threads: 4, max_batch_size: 1 });
assert.equal(model.source.lifecycle.unload, 'manual');
const selected = selectModelReference(model, 'image_embeddings/family-model', true);
assert.equal(selected.name, 'family-model');
assert.equal(selectModelReference(model, 'image_embeddings/typing', false).name, '');
const edited = { ...selected, name: 'Chosen name', parameters: { unload_other_tower_on_call: false },
  source: { ...selected.source, execution_options: { device: 'cpu', intraop_threads: 2, max_batch_size: 8 },
    lifecycle: { unload: 'idle', idle_seconds: 75 } } };
const changed = selectModelReference(edited, 'image_embeddings/another', true);
assert.equal(changed.name, edited.name);
assert.deepEqual(changed.source, edited.source);
assert.deepEqual(changed.parameters, edited.parameters);
const unbound = selectModelSource(selected, null);
assert.equal(unbound.model_ref, selected.model_ref);
assert.deepEqual(selectModelSource(unbound, localSource()), selected);
assert.equal(selectModelSource(edited, localSource()), edited);

for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  let changedParameters;
  const tree = ProfileParameters({ value: edited, onChange: (value) => { changedParameters = value; } });
  const switches = descendants(tree).filter((node) => node.type === Switch);
  assert.equal(switches.length, 1);
  assert.equal(switches[0].props.checked, false);
  switches[0].props.onCheckedChange(true);
  assert.deepEqual(changedParameters, { unload_other_tower_on_call: true });
  const markup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: model, onChange() {} }));
  const t = i18n.getFixedT(locale, 'llm');
  assert.ok(markup.includes(t('siglip.unloadOtherHint')));
  assert.ok(renderToStaticMarkup(React.createElement(SiglipInspectionPanel, { modelRef: 'image_embeddings/test' })).includes(t('siglip.inspecting')));
  for (const key of ['architecture', 'dimensions', 'normalize', 'batch_size']) assert.ok(!markup.includes(t('params.' + key)));
}
await modelsApi.inspectImageEmbedding('image_embeddings/模型');
assert.equal(new URL(calls.at(-1)[0], 'http://test').searchParams.get('model_ref'), 'image_embeddings/模型');
await modelsApi.modelAction('model-id', 'load', 'text');
assert.equal(calls.at(-1)[1].body, '{"tower":"text"}');
await modelsApi.modelAction('model-id', 'unload');
assert.equal(calls.at(-1)[1].body, undefined);
await modelsApi.getModelLog('model-id', 'image');
assert.equal(calls.at(-1)[0], '/api/models/profiles/model-id/log?tower=image');
console.log('SigLIP local defaults, preserved drafts, bilingual switch and tower API requests passed.');
