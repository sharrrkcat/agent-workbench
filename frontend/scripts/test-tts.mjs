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
const { kinds, newModel, applyDirectoryInspection, localEngine, localSource, selectModelSource } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const { DirectoryInspectionPanel } = (await load('../src/components/settings/models/DirectoryInspection.tsx')).exports;
const { SelectItem } = (await load('../src/components/ui/select.tsx')).exports;
function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!React.isValidElement(node)) return [];
  return [node, ...descendants(node.props.children)];
}
assert.ok(kinds.includes('tts'));
const information = (engine) => ({ kind: 'tts', model_ref: `tts/${engine}`, engine, architecture: engine, diagnostics: [] });
const draft = newModel('tts');
assert.equal(localEngine(draft), null);
assert.deepEqual(draft.source.execution_options, {});
const profile = applyDirectoryInspection(draft, information('kokoro'), true, false);
assert.equal(profile.source.type, 'local');
assert.equal(localEngine(profile, 'kokoro'), 'kokoro');
assert.equal(profile.source.execution_options.max_batch_size, 1);
assert.deepEqual(profile.parameters, { speed: 1, response_format: 'mp3' });
const chatterbox = applyDirectoryInspection({ ...profile, parameters: { ...profile.parameters, speed: 0.8 } }, information('chatterbox'), true, false);
assert.ok(!('architecture' in chatterbox.parameters));
assert.equal(chatterbox.parameters.speed, 0.8);
assert.equal(chatterbox.parameters.seed, null);
assert.deepEqual(chatterbox.source.execution_options, { device: 'cuda', intraop_threads: 4 });
const kokoro = applyDirectoryInspection({ ...chatterbox, parameters: { ...chatterbox.parameters, cfg_weight: 0.3 } }, information('kokoro'), true, false);
assert.equal(kokoro.parameters.speed, 0.8);
assert.ok(!('cfg_weight' in kokoro.parameters) && !('seed' in kokoro.parameters));
assert.deepEqual(kokoro.source.execution_options, { device: 'cpu', intraop_threads: 4, max_batch_size: 1 });
const qwen = applyDirectoryInspection(chatterbox, information('qwen3tts'), true, false);
assert.deepEqual(qwen.parameters, { speed: 0.8, response_format: 'mp3',
  seed: null, do_sample: true, temperature: 0.9, top_p: 1, top_k: 50, repetition_penalty: 1.05, max_new_tokens: 2048 });
const editedQwen = { ...qwen, parameters: { ...qwen.parameters, seed: 0, top_k: 0, max_new_tokens: 4096 } };
assert.deepEqual(selectModelSource(editedQwen, localSource()).parameters, editedQwen.parameters);
assert.deepEqual(applyDirectoryInspection(editedQwen, information('qwen3tts'), false, false), editedQwen);
const back = applyDirectoryInspection(editedQwen, information('chatterbox'), true, false).parameters;
assert.equal(back.temperature, 0.8);
assert.equal(back.speed, 0.8);
assert.equal(back.seed, null);
assert.ok(!('top_k' in back) && !('max_new_tokens' in back) && !('do_sample' in back));
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const t = i18n.getFixedT(locale, 'llm');
  const markup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: profile, engine: 'kokoro', onChange: () => {} }));
  assert.ok(markup.includes(t('params.speed')) && markup.includes(t('params.response_format')));
  assert.ok(markup.includes('MP3'));
  const details = renderToStaticMarkup(React.createElement(DirectoryInspectionPanel, { information: information('kokoro') }));
  assert.ok(details.includes(t('directory.information')) && details.includes('kokoro'));
  assert.ok(!details.includes('<input') && !details.includes('<select'));
  const options = descendants(ProfileParameters({ value: profile, onChange() {} })).filter((node) => node.type === SelectItem);
  assert.deepEqual(options.filter((node) => ['mp3', 'wav'].includes(node.props.value)).map((node) => node.props.children), ['MP3', 'WAV']);
  assert.ok(!markup.includes(t('params.batch_size')) && !markup.includes(t('params.temperature')) && !markup.includes(t('params.seed')));
  const audioMarkup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: chatterbox, engine: 'chatterbox', onChange: () => {} }));
  for (const key of ['seed', 'exaggeration', 'cfg_weight', 'temperature', 'repetition_penalty', 'min_p', 'top_p']) {
    assert.ok(audioMarkup.includes(t('params.' + key)), `${locale}: ${key}`);
  }
  assert.match(audioMarkup, /min="0.01" max="5"/);
  assert.match(audioMarkup, /min="0" max="4294967295"/);
  const qwenMarkup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: qwen, engine: 'qwen3tts', onChange: () => {} }));
  for (const key of ['seed', 'do_sample', 'temperature', 'top_p', 'top_k', 'repetition_penalty', 'max_new_tokens']) {
    assert.ok(qwenMarkup.includes(t('params.' + key)), `${locale}: Qwen ${key}`);
  }
  assert.ok(!qwenMarkup.includes(t('params.exaggeration')) && !qwenMarkup.includes(t('params.cfg_weight')));
  assert.ok(!qwenMarkup.includes(t('directory.fields.architecture')));
  assert.match(qwenMarkup, /max="8192"/);
}
let requested;
globalThis.fetch = async (url) => { requested = url; return new Response('[]', { headers: { 'Content-Type': 'application/json' } }); };
const { modelsApi } = (await load('../src/api/models.ts')).exports;
await modelsApi.getModelVoices('model/id');
assert.equal(requested, '/api/models/profiles/model%2Fid/voices');
await modelsApi.inspectLocalDirectory('tts', 'tts/本地模型');
assert.equal(new URL(requested, 'http://test').searchParams.get('model_ref'), 'tts/本地模型');
console.log('TTS defaults, runtime binding, bilingual parameters and voice API passed.');
