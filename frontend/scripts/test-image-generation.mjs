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
const { newModel, localEngine, selectModelSource } = (await load('../src/components/settings/models/profileDefaults.ts')).exports;
const { ProfileParameters } = (await load('../src/components/settings/models/ProfileParameters.tsx')).exports;
const draft = newModel('image_generation');
assert.equal(draft.source, null);
assert.equal(draft.request_options, null);
assert.deepEqual(draft.parameters, { n: 1 });
const bound = selectModelSource(draft, { type: 'provider', provider_profile_id: 'one' }, true);
assert.equal(localEngine(bound), null);
const edited = { ...bound, model_ref: 'image-id', parameters: { n: 2, size: 'auto', response_format: 'b64_json' } };
const changed = selectModelSource(edited, { type: 'provider', provider_profile_id: 'two' });
assert.equal(changed.model_ref, '');
assert.deepEqual(changed.parameters, edited.parameters);
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  const html = renderToStaticMarkup(React.createElement(ProfileParameters, { value: draft, onChange() {} }));
  assert.ok(html.includes(resources[locale].llm.imageGeneration.n));
  assert.ok(html.includes(resources[locale].llm.imageGeneration.providerDefault));
  assert.doesNotMatch(html, /imageGeneration\./);
}
console.log('Image generation defaults and bilingual fields passed.');
