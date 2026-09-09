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
const { newModel, selectManagedRuntime, runtimeFamilyKey } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const entry = { runtime_id: 'python-worker', variant: 'transformers-cuda', supported: true, kinds: ['llm'],
  options_schema: { properties: { device: { default: 'cuda' }, intraop_threads: { default: 4 } } } };
const original = { ...newModel('llm'), provider_profile_id: 'external', parameters: { max_tokens: 128, presence_penalty: 1 },
  capabilities: { streaming: true, tools: true, vision: true, json_object: true, json_schema: true } };
const selected = selectManagedRuntime(original, entry);
assert.equal(selected.provider_profile_id, null);
assert.equal(selected.runtime_id, 'python-worker');
assert.equal(selected.runtime_variant, 'transformers-cuda');
assert.deepEqual(selected.runtime_options, { device: 'cuda', intraop_threads: 4 });
assert.deepEqual(selected.parameters, { max_tokens: 128 });
assert.deepEqual(selected.capabilities, { streaming: true, tools: true, vision: false, json_object: false, json_schema: false });
assert.equal(selected.lifecycle.unload, 'manual');
assert.equal(original.parameters.presence_penalty, 1);
assert.throws(() => selectManagedRuntime(original, { ...entry, variant: 'infinity-cuda', supported: false }));
const llama = selectManagedRuntime(selected, { runtime_id: 'llama-server', variant: 'cuda', supported: true, kinds: ['llm'],
  options_schema: { properties: { gpu_layers: { default: 'auto' }, threads: { default: 4 } } } });
assert.equal(llama.runtime_id, 'llama-server');
assert.deepEqual(llama.runtime_options, { gpu_layers: 'auto', threads: 4 });
assert.equal(runtimeFamilyKey('python-worker', 'transformers-cuda'), 'transformers-cuda');
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const t = i18n.getFixedT(locale, 'llm');
  const html = renderToStaticMarkup(React.createElement(ProfileParameters, { value: selected, onChange: () => {} }));
  assert.ok(html.includes(t('params.max_tokens')));
  assert.ok(!html.includes(t('params.presence_penalty')) && !html.includes(t('params.frequency_penalty')));
  const vision = renderToStaticMarkup(React.createElement(ProfileParameters, { value: newModel('vision'), onChange: () => {} }));
  const embedding = renderToStaticMarkup(React.createElement(ProfileParameters, { value: newModel('image_embedding'), onChange: () => {} }));
  assert.ok(vision.includes('wd14') && vision.includes(t('visionTags')));
  assert.ok(embedding.includes('clip') && embedding.includes('siglip2'));
  assert.doesNotMatch(vision + embedding, /florence|dinov2|caption/i);
}
console.log('Transformers selection, strict device defaults, retained entries and bilingual parameter controls passed.');
