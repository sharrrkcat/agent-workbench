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
const { kinds, newModel, updateModel, localEngine, selectTTSArchitecture } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
assert.ok(kinds.includes('tts'));
const profile = newModel('tts');
assert.equal(profile.backend_profile_id, 'local');
assert.equal(localEngine(profile), 'kokoro');
assert.equal(profile.execution_options.max_batch_size, 1);
assert.deepEqual(profile.parameters, { architecture: 'kokoro', speed: 1, response_format: 'mp3' });
const chatterbox = updateModel(profile, { parameters: selectTTSArchitecture({ ...profile.parameters, speed: 0.8 }, 'chatterbox') });
assert.equal(chatterbox.parameters.architecture, 'chatterbox');
assert.equal(chatterbox.parameters.speed, 0.8);
assert.equal(chatterbox.parameters.seed, null);
assert.deepEqual(chatterbox.execution_options, { device: 'cuda', intraop_threads: 4 });
const kokoro = updateModel(chatterbox, { parameters: selectTTSArchitecture({ ...chatterbox.parameters, cfg_weight: 0.3 }, 'kokoro') });
assert.equal(kokoro.parameters.architecture, 'kokoro');
assert.equal(kokoro.parameters.speed, 0.8);
assert.ok(!('cfg_weight' in kokoro.parameters) && !('seed' in kokoro.parameters));
assert.deepEqual(kokoro.execution_options, { device: 'cpu', intraop_threads: 4, max_batch_size: 1 });
const qwen = updateModel(chatterbox, { parameters: selectTTSArchitecture(chatterbox.parameters, 'qwen3tts') });
assert.deepEqual(qwen.parameters, { architecture: 'qwen3tts', speed: 0.8, response_format: 'mp3',
  seed: null, do_sample: true, temperature: 0.9, top_p: 1, top_k: 50, repetition_penalty: 1.05, max_new_tokens: 2048 });
const editedQwen = { ...qwen, parameters: { ...qwen.parameters, seed: 0, top_k: 0, max_new_tokens: 4096 } };
assert.deepEqual(updateModel(editedQwen, { backend_profile_id: 'local' }).parameters, editedQwen.parameters);
const back = selectTTSArchitecture(editedQwen.parameters, 'chatterbox');
assert.equal(back.temperature, 0.8);
assert.equal(back.speed, 0.8);
assert.equal(back.seed, null);
assert.ok(!('top_k' in back) && !('max_new_tokens' in back) && !('do_sample' in back));
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const t = i18n.getFixedT(locale, 'llm');
  const markup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: profile, onChange: () => {} }));
  assert.ok(markup.includes(t('params.speed')) && markup.includes(t('params.response_format')));
  assert.ok(markup.includes('MP3') && markup.includes('WAV') && markup.includes('Kokoro-82M'));
  assert.ok(!markup.includes(t('params.batch_size')) && !markup.includes(t('params.temperature')) && !markup.includes(t('params.seed')));
  const audioMarkup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: chatterbox, onChange: () => {} }));
  for (const key of ['seed', 'exaggeration', 'cfg_weight', 'temperature', 'repetition_penalty', 'min_p', 'top_p']) {
    assert.ok(audioMarkup.includes(t('params.' + key)), `${locale}: ${key}`);
  }
  assert.ok(audioMarkup.includes(t('chatterboxEnglish')));
  assert.match(audioMarkup, /min="0.01" max="5"/);
  assert.match(audioMarkup, /min="0" max="4294967295"/);
  const qwenMarkup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: qwen, onChange: () => {} }));
  for (const key of ['seed', 'do_sample', 'temperature', 'top_p', 'top_k', 'repetition_penalty', 'max_new_tokens']) {
    assert.ok(qwenMarkup.includes(t('params.' + key)), `${locale}: Qwen ${key}`);
  }
  assert.ok(!qwenMarkup.includes(t('params.exaggeration')) && !qwenMarkup.includes(t('params.cfg_weight')));
  assert.ok(qwenMarkup.includes(t('qwen3TTSBase')));
  assert.match(qwenMarkup, /value="qwen3tts" selected=""/);
  assert.match(qwenMarkup, /max="8192"/);
}
let requested;
globalThis.fetch = async (url) => { requested = url; return new Response('[]', { headers: { 'Content-Type': 'application/json' } }); };
const { modelsApi } = (await load('../src/api/models.ts')).exports;
await modelsApi.getModelVoices('model/id');
assert.equal(requested, '/api/models/profiles/model%2Fid/voices');
console.log('TTS defaults, runtime binding, bilingual parameters and voice API passed.');
