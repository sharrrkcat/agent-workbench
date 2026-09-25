import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule } from './module-loader.mjs';

const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale, { llm:
  JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8')),
}]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', interpolation: { escapeValue: false } });
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
});
const { newModel, updateModel, applyDirectoryInspection, localEngine, localSource, localOnly, selectModelSource } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const original = { ...newModel('llm'), source: null, model_ref: 'llms/model', parameters: { max_tokens: 128, presence_penalty: 1 },
  capabilities: { streaming: true, tools: true, vision: true, json_object: true, json_schema: true } };
const bound = selectModelSource(original, localSource());
assert.equal(localEngine(bound), null);
const selected = applyDirectoryInspection(bound, { kind: 'llm', model_ref: 'llms/model', engine: 'transformers', architecture: 'Qwen', main_model_ref: null, mmproj_ref: null, model_files: [], diagnostics: [] }, true, false);
assert.equal(selected.source.type, 'local');
assert.equal(localEngine(selected, 'transformers'), 'transformers');
assert.deepEqual(selected.source.execution_options, { device: 'cuda', intraop_threads: 4 });
assert.deepEqual(selected.parameters, { max_tokens: 128 });
assert.deepEqual(selected.capabilities, { streaming: true, tools: true, vision: true, json_object: false, json_schema: false });
assert.equal(selected.source.lifecycle.unload, 'manual');
assert.equal(original.parameters.presence_penalty, 1);
const info = { kind: 'llm', model_ref: 'llms/gguf', engine: 'llama-server', architecture: null,
  main_model_ref: 'llms/gguf/model.gguf', mmproj_ref: 'llms/gguf/mmproj.gguf', model_files: ['llms/gguf/model.gguf'], diagnostics: [] };
const llama = applyDirectoryInspection(updateModel(selected, { model_ref: info.model_ref }), info, true, true);
assert.equal(localEngine(llama, info.engine), 'llama-server');
assert.deepEqual(llama.source.execution_options, { device: 'cuda', gpu_layers: 'auto', threads: 4, context_size: 4096, batch_size: 512 });
assert.equal(llama.capabilities.vision, true);
assert.equal(updateModel(llama, { name: 'Rename' }).capabilities.vision, true);
const textOnly = updateModel(llama, { capabilities: { ...llama.capabilities, vision: false } });
assert.equal(applyDirectoryInspection(textOnly, info, false, false).capabilities.vision, false);
assert.equal(applyDirectoryInspection(textOnly, info, true, true).capabilities.vision, true);
assert.equal(applyDirectoryInspection(llama, { ...info, mmproj_ref: null }, false, false).capabilities.vision, false);
assert.deepEqual(['llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts', 'asr'].filter(localOnly), ['image_embedding', 'vision', 'tts', 'asr']);
const external = selectModelSource(llama, { type: 'provider', provider_profile_id: 'external' });
assert.equal(localEngine(external), null);
assert.deepEqual(external.source, { type: 'provider', provider_profile_id: 'external' });
assert.equal(external.model_ref, '');
const manual = { ...external, model_ref: 'manual-id' };
assert.equal(selectModelSource(manual, null).model_ref, 'manual-id');
assert.equal(selectModelSource(manual, manual.source), manual);
assert.equal(selectModelSource(manual, { type: 'provider', provider_profile_id: 'second' }).model_ref, '');
assert.equal(updateModel(selected, { name: 'Renamed' }).source.execution_options, selected.source.execution_options);
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const t = i18n.getFixedT(locale, 'llm');
  const html = renderToStaticMarkup(React.createElement(ProfileParameters, { value: selected, engine: 'transformers', onChange: () => {} }));
  assert.ok(html.includes(t('params.max_tokens')));
  assert.ok(!html.includes(t('params.presence_penalty')) && !html.includes(t('params.frequency_penalty')));
  const vision = renderToStaticMarkup(React.createElement(ProfileParameters, { value: newModel('vision'), onChange: () => {} }));
  assert.ok(vision.includes(t('visionTags')));
  assert.doesNotMatch(vision, /florence|dinov2|caption/i);
}
console.log('Transformers selection, strict device defaults, retained entries and bilingual parameter controls passed.');
