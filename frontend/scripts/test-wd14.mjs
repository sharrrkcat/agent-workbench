import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { createModuleLoader, mockModule } from './module-loader.mjs';

const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale, {
  llm: JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8')),
}]));
const i18n = i18next.createInstance();
await i18n.init({ resources, lng: 'en', interpolation: { escapeValue: false } });
const load = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
});
const { newModel, applyDirectoryInspection, localEngine, localSource, localOnly, selectModelSource, updateModel } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const { Input } = (await load('../src/components/ui/input.tsx')).exports;
const { FieldLabel } = (await load('../src/components/ui/field.tsx')).exports;

function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!React.isValidElement(node)) return [];
  return [node, ...descendants(node.props.children)];
}

const draft = newModel('vision');
assert.equal(localEngine(draft), null);
assert.ok(localOnly('vision'));
const profile = applyDirectoryInspection(draft, { kind: 'vision', model_ref: 'vision/tagger', engine: 'wd14', architecture: 'wd14', backbone: null, diagnostics: [] }, true, false);
assert.equal(localEngine(profile, 'wd14'), 'wd14');
assert.deepEqual(profile.source.execution_options, { device: 'cpu', intraop_threads: 4, max_batch_size: 1 });
assert.equal(profile.source.lifecycle.unload, 'manual');
assert.deepEqual(profile.parameters, { task: 'tags', thresholds: { general: 0.35, character: 0.85 } });
const withReference = updateModel(profile, { model_ref: 'vision/another-family-model' });
assert.equal(selectModelSource(withReference, localSource()), withReference);

for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const t = i18n.getFixedT(locale, 'llm');
  let changed;
  const tree = ProfileParameters({ value: profile, onChange: (parameters) => { changed = parameters; } });
  const controls = descendants(tree).filter((node) => node.type === Input && node.props.type === 'number');
  assert.equal(controls.length, 2);
  assert.deepEqual(controls.map((node) => node.props.value), [0.35, 0.85]);
  for (const input of controls) {
    assert.equal(input.props.min, 0);
    assert.equal(input.props.max, 1);
    assert.equal(input.props.step, 'any');
    assert.equal(input.props.required, true);
  }
  controls[0].props.onChange({ currentTarget: { value: '0' } });
  assert.deepEqual(changed.thresholds, { general: 0, character: 0.85 });
  controls[1].props.onChange({ currentTarget: { value: '0.857' } });
  assert.deepEqual(changed.thresholds, { general: 0.35, character: 0.857 });
  controls[0].props.onChange({ currentTarget: { value: '' } });
  assert.ok(Number.isNaN(changed.thresholds.general));
  const blank = ProfileParameters({ value: { ...profile, parameters: changed }, onChange() {} });
  assert.equal(descendants(blank).find((node) => node.type === Input && node.props.type === 'number').props.value, '');
  const labels = descendants(tree).filter((node) => node.type === FieldLabel).map((node) => node.props.children);
  assert.ok(labels.includes(t('tagThresholds.general')) && labels.includes(t('tagThresholds.character')));
  assert.ok(!labels.includes(t('params.batch_size')));
  const markup = renderToStaticMarkup(React.createElement(ProfileParameters, { value: profile, onChange() {} }));
  assert.ok(markup.includes(t('visionTags')) && !markup.includes(t('directory.fields.architecture')));
}
console.log('WD14 CPU defaults, source changes, bilingual thresholds, zero and native validation passed.');
