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
const { kinds, newModel, selectManagedRuntime } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
assert.ok(kinds.includes('tts'));
const profile = newModel('tts');
assert.equal(profile.runtime_variant, 'onnx-cpu');
assert.equal(profile.runtime_id, 'python-worker');
assert.equal(profile.runtime_options.max_batch_size, 1);
assert.deepEqual(profile.parameters, { architecture: 'kokoro', speed: 1, response_format: 'mp3' });
const audioEntry = { runtime_id: 'python-worker', variant: 'audio-cuda', supported: true, kinds: ['tts'],
  options_schema: { properties: { device: { default: 'cuda' }, intraop_threads: { default: 4 } } } };
const chatterbox = selectManagedRuntime({ ...profile, parameters: { ...profile.parameters, speed: 0.8 } }, audioEntry);
assert.equal(chatterbox.parameters.architecture, 'chatterbox');
assert.equal(chatterbox.parameters.speed, 0.8);
assert.deepEqual(chatterbox.runtime_options, { device: 'cuda', intraop_threads: 4 });
const kokoro = selectManagedRuntime({ ...chatterbox, parameters: { ...chatterbox.parameters, cfg_weight: 0.3 } }, {
  ...audioEntry, variant: 'onnx-cpu', options_schema: { properties: { device: { default: 'cpu' }, max_batch_size: { default: 1 } } },
});
assert.equal(kokoro.parameters.architecture, 'kokoro');
assert.equal(kokoro.parameters.speed, 0.8);
assert.ok(!('cfg_weight' in kokoro.parameters));
assert.throws(() => selectManagedRuntime(profile, { ...audioEntry, supported: false }));
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const t = i18n.getFixedT(locale, 'llm');
  const markup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: profile, onChange: () => {} }));
  assert.ok(markup.includes(t('params.speed')) && markup.includes(t('params.response_format')));
  assert.ok(markup.includes('MP3') && markup.includes('WAV') && markup.includes('Kokoro-82M'));
  assert.ok(!markup.includes(t('params.batch_size')) && !markup.includes(t('params.temperature')));
  const audioMarkup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: chatterbox, onChange: () => {} }));
  for (const key of ['exaggeration', 'cfg_weight', 'temperature', 'repetition_penalty', 'min_p', 'top_p']) {
    assert.ok(audioMarkup.includes(t('params.' + key)), `${locale}: ${key}`);
  }
  assert.ok(audioMarkup.includes(t('chatterboxEnglish')));
  assert.match(audioMarkup, /min="0.01" max="5"/);
}
let requested;
globalThis.fetch = async (url) => { requested = url; return new Response('[]', { headers: { 'Content-Type': 'application/json' } }); };
const { modelsApi } = (await load('../src/api/models.ts')).exports;
await modelsApi.getModelVoices('model/id');
assert.equal(requested, '/api/models/profiles/model%2Fid/voices');
console.log('TTS defaults, runtime binding, bilingual parameters and voice API passed.');
