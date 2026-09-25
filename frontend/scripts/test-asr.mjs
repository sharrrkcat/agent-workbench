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
const { ASRInspectionPanel } = (await load('../src/components/settings/models/ASRInspection.tsx')).exports;
const { modelsApi } = (await load('../src/api/models.ts')).exports;

const model = newModel('asr');
assert.equal(localEngine(model), 'whisper');
assert.equal(model.external_enabled, false);
assert.deepEqual(model.source.execution_options, { device: 'cuda', intraop_threads: 4 });
assert.equal(model.source.lifecycle.unload, 'manual');
assert.deepEqual(model.parameters, { language: 'auto', prompt: '', temperature: 0, response_format: 'json' });
const selected = selectModelReference(model, 'asr/native-directory', true);
assert.equal(selected.name, 'native-directory');
const edited = { ...selected, name: 'My ASR', parameters: { language: 'zh', prompt: 'context', temperature: 0.4, response_format: 'verbose_json' } };
const changed = selectModelReference(edited, 'asr/another-model', true);
assert.equal(changed.name, edited.name);
assert.deepEqual(changed.source, edited.source);
assert.deepEqual(changed.parameters, edited.parameters);
const unbound = selectModelSource(edited, null);
assert.equal(localEngine(unbound), null);
assert.equal(unbound.model_ref, edited.model_ref);
assert.equal(localEngine(selectModelSource(unbound, localSource())), 'whisper');
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  for (const value of [model, edited, unbound]) {
    const markup = renderToStaticMarkup(React.createElement(ProfileParameters, { value, onChange() {} }));
    for (const key of ['asr.language', 'asr.prompt', 'asr.responseFormat', 'asr.timestampsHint', 'asr.defaultsHint', 'params.temperature']) {
      assert.ok(markup.includes(i18n.t(key, { ns: 'llm' })), key);
    }
    assert.ok(!markup.includes('name="architecture"'));
  }
  const markup = renderToStaticMarkup(React.createElement(ASRInspectionPanel, { modelRef: selected.model_ref }));
  assert.ok(markup.includes(i18n.t('asr.information', { ns: 'llm' })));
  assert.ok(markup.includes(i18n.t('asr.inspecting', { ns: 'llm' })));
}
await modelsApi.inspectASR('asr/本地模型');
assert.deepEqual([...new URL(calls.at(-1)[0], 'http://test').searchParams], [['kind', 'asr'], ['model_ref', 'asr/本地模型']]);
console.log('ASR defaults, directory selection, generation controls, locales and inspection requests passed.');
